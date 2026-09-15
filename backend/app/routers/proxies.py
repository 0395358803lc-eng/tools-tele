from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy

from ..audit import log_audit
from ..db import get_db
from ..models import Account, AccountProxy
from ..quota import assert_proxy_capacity
from ..proxy_store import public_proxy, runtime_proxy_from_row, save_proxy, mark_proxy_status, set_active_slot, has_fallback
from ..tg_manager import manager
from ..utils import friendly_error

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


class ProxyUpdateIn(BaseModel):
    enabled: bool = True
    proxy_type: str = "socks5"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=512)
    clear_password: bool = False
    rdns: bool = True
    fallback_enabled: bool = False
    fallback_proxy_type: str = "socks5"
    fallback_host: str = Field(default="", max_length=255)
    fallback_port: int = Field(default=1080, ge=1, le=65535)
    fallback_username: str | None = Field(default=None, max_length=255)
    fallback_password: str | None = Field(default=None, max_length=512)
    clear_fallback_password: bool = False
    fallback_rdns: bool = True


async def _account_or_404(db: AsyncSession, account_id: int) -> Account:
    acc = await db.get(Account, account_id)
    if not acc or acc.deleted_at is not None:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    return acc


@router.get("")
async def list_proxies(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Account, AccountProxy)
        .outerjoin(AccountProxy, AccountProxy.account_id == Account.id)
        .where(Account.deleted_at.is_(None))
        .order_by(Account.id)
    )).all()
    return [{
        "account": {
            "id": acc.id,
            "phone": acc.phone,
            "name": (f"{acc.first_name or ''} {acc.last_name or ''}".strip() or acc.phone),
            "username": acc.username or "",
            "status": acc.status,
        },
        "proxy": public_proxy(proxy),
    } for acc, proxy in rows]


@router.put("/{account_id}")
async def put_proxy(account_id: int, body: ProxyUpdateIn, db: AsyncSession = Depends(get_db)):
    await _account_or_404(db, account_id)
    await assert_proxy_capacity(account_id)
    try:
        row = await save_proxy(
            db, account_id,
            enabled=body.enabled,
            proxy_type=body.proxy_type,
            host=body.host,
            port=body.port,
            username=body.username,
            password=body.password,
            clear_password=body.clear_password,
            rdns=body.rdns,
            fallback_enabled=body.fallback_enabled,
            fallback_proxy_type=body.fallback_proxy_type,
            fallback_host=body.fallback_host,
            fallback_port=body.fallback_port,
            fallback_username=body.fallback_username,
            fallback_password=body.fallback_password,
            clear_fallback_password=body.clear_fallback_password,
            fallback_rdns=body.fallback_rdns,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    await log_audit("proxy:save", account_id, {
        "proxy_type": row.proxy_type,
        "host": row.host,
        "port": row.port,
        "enabled": row.enabled,
        "has_username": bool(row.username),
        "has_password": bool(row.password_ciphertext),
    })
    return public_proxy(row)


@router.delete("/{account_id}")
async def delete_proxy(account_id: int, db: AsyncSession = Depends(get_db)):
    await _account_or_404(db, account_id)
    row = await db.get(AccountProxy, account_id)
    if row:
        await db.delete(row)
        await db.commit()
    await log_audit("proxy:delete", account_id)
    return {"ok": True}


def _python_socks_type(kind: str):
    return {
        "socks5": ProxyType.SOCKS5,
        "socks4": ProxyType.SOCKS4,
        "http": ProxyType.HTTP,
    }[kind]


@router.post("/{account_id}/test")
async def test_proxy(account_id: int, db: AsyncSession = Depends(get_db)):
    await _account_or_404(db, account_id)
    row = await db.get(AccountProxy, account_id)
    if not row or not row.enabled:
        raise HTTPException(409, "Proxy chưa được cấu hình hoặc đang tắt")
    try:
        cfg = runtime_proxy_from_row(row)
        cli = manager.get(account_id)
        target_host = getattr(getattr(cli, "session", None), "server_address", None) or "149.154.167.51"
        target_port = int(getattr(getattr(cli, "session", None), "port", None) or 443)
        proxy = Proxy.create(
            _python_socks_type(cfg["proxy_type"]), cfg["addr"], cfg["port"],
            cfg.get("username"), cfg.get("password"), cfg.get("rdns", True),
        )
        sock = await proxy.connect(dest_host=target_host, dest_port=target_port, timeout=12)
        try:
            sock.close()
        except Exception:
            pass
        await mark_proxy_status(account_id, "test_ok")
        await log_audit("proxy:test", account_id, {"result": "ok"})
        return {"ok": True, "target": f"{target_host}:{target_port}"}
    except Exception as exc:
        await mark_proxy_status(account_id, "test_failed", str(exc))
        await log_audit("proxy:test", account_id, {"result": "failed", "error_type": type(exc).__name__})
        raise HTTPException(400, "Kiểm tra proxy thất bại: " + friendly_error(exc))


@router.post("/{account_id}/test-fallback")
async def test_fallback_proxy(account_id: int, db: AsyncSession = Depends(get_db)):
    await _account_or_404(db, account_id)
    row = await db.get(AccountProxy, account_id)
    if not row or not has_fallback(row):
        raise HTTPException(409, "Proxy dự phòng chưa được cấu hình")
    try:
        cfg = runtime_proxy_from_row(row, "fallback")
        cli = manager.get(account_id)
        target_host = getattr(getattr(cli, "session", None), "server_address", None) or "149.154.167.51"
        target_port = int(getattr(getattr(cli, "session", None), "port", None) or 443)
        proxy = Proxy.create(_python_socks_type(cfg["proxy_type"]), cfg["addr"], cfg["port"],
            cfg.get("username"), cfg.get("password"), cfg.get("rdns", True))
        sock = await proxy.connect(dest_host=target_host, dest_port=target_port, timeout=12)
        try:
            sock.close()
        except Exception:
            pass
        await log_audit("proxy:test_fallback", account_id, {"result": "ok"})
        return {"ok": True, "target": f"{target_host}:{target_port}"}
    except Exception as exc:
        await log_audit("proxy:test_fallback", account_id, {
            "result": "failed", "error_type": type(exc).__name__,
        })
        raise HTTPException(400, "Kiểm tra proxy dự phòng thất bại: " + friendly_error(exc))


class ProxySlotIn(BaseModel):
    slot: str


@router.post("/{account_id}/switch")
async def switch_proxy(account_id: int, body: ProxySlotIn, db: AsyncSession = Depends(get_db)):
    await _account_or_404(db, account_id)
    slot = (body.slot or "").strip().lower()
    if slot not in {"primary", "fallback"}:
        raise HTTPException(400, "slot phải là primary hoặc fallback")
    if not await set_active_slot(account_id, slot, failover=(slot == "fallback")):
        raise HTTPException(409, "Không thể chuyển sang proxy được chọn")
    try:
        await manager.reconnect_account(account_id)
    except Exception as exc:
        raise HTTPException(400, "Đã đổi cấu hình nhưng reconnect thất bại: " + friendly_error(exc))
    await log_audit("proxy:switch", account_id, {"slot": slot})
    row = await db.get(AccountProxy, account_id)
    return public_proxy(row)


@router.post("/{account_id}/apply")
async def apply_proxy(account_id: int, db: AsyncSession = Depends(get_db)):
    acc = await _account_or_404(db, account_id)
    try:
        cli = await manager.reconnect_account(account_id)
        me = await asyncio.wait_for(cli.get_me(), timeout=20)
        row = await db.get(AccountProxy, account_id)
        if row and row.enabled:
            await mark_proxy_status(account_id, "connected")
        await log_audit("proxy:apply", account_id, {"enabled": bool(row and row.enabled)})
        return {
            "ok": True,
            "account_id": account_id,
            "telegram_user_id": getattr(me, "id", None),
            "via_proxy": bool(row and row.enabled),
        }
    except Exception as exc:
        await mark_proxy_status(account_id, "connect_failed", str(exc))
        await log_audit("proxy:apply", account_id, {"result": "failed", "error_type": type(exc).__name__})
        raise HTTPException(400, "Không thể kết nối Telegram với cấu hình hiện tại: " + friendly_error(exc))
