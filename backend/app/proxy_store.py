from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import AsyncSessionLocal
from .models import AccountProxy
from .secrets_store import encrypt_value, decrypt_value
from .time_utils import utcnow

SUPPORTED_PROXY_TYPES = {"socks5", "socks4", "http"}


def validate_proxy(proxy_type: str, host: str, port: int) -> tuple[str, str, int]:
    ptype = (proxy_type or "").strip().lower()
    if ptype not in SUPPORTED_PROXY_TYPES:
        raise ValueError("Loại proxy phải là SOCKS5, SOCKS4 hoặc HTTP")
    clean_host = (host or "").strip()
    if not clean_host or len(clean_host) > 255:
        raise ValueError("Host proxy không hợp lệ")
    try:
        clean_port = int(port)
    except Exception as exc:
        raise ValueError("Cổng proxy không hợp lệ") from exc
    if clean_port < 1 or clean_port > 65535:
        raise ValueError("Cổng proxy phải nằm trong khoảng 1–65535")
    return ptype, clean_host, clean_port


def public_proxy(row: AccountProxy | None) -> dict | None:
    if not row:
        return None
    return {
        "account_id": row.account_id,
        "enabled": bool(row.enabled),
        "proxy_type": row.proxy_type,
        "host": row.host,
        "port": row.port,
        "username": row.username or "",
        "has_password": bool(row.password_ciphertext),
        "rdns": bool(row.rdns),
        "last_status": row.last_status or "unknown",
        "last_error": row.last_error or "",
        "last_checked_at": row.last_checked_at,
        "updated_at": row.updated_at,
    }


def runtime_proxy_from_row(row: AccountProxy | None) -> dict | None:
    if not row or not row.enabled:
        return None
    password = decrypt_value(row.password_ciphertext) if row.password_ciphertext else None
    return {
        "proxy_type": row.proxy_type,
        "addr": row.host,
        "port": int(row.port),
        "rdns": bool(row.rdns),
        "username": row.username or None,
        "password": password,
    }


async def get_row(account_id: int, db: AsyncSession | None = None) -> AccountProxy | None:
    if db is not None:
        return await db.get(AccountProxy, account_id)
    async with AsyncSessionLocal() as own:
        return await own.get(AccountProxy, account_id)


async def runtime_proxy(account_id: int) -> dict | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AccountProxy, account_id)
        return runtime_proxy_from_row(row)


async def save_proxy(
    db: AsyncSession,
    account_id: int,
    *,
    enabled: bool,
    proxy_type: str,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    clear_password: bool,
    rdns: bool,
) -> AccountProxy:
    ptype, clean_host, clean_port = validate_proxy(proxy_type, host, port)
    user = (username or "").strip()[:255] or None
    row = await db.get(AccountProxy, account_id)
    now = utcnow()
    if not row:
        row = AccountProxy(
            account_id=account_id,
            enabled=enabled,
            proxy_type=ptype,
            host=clean_host,
            port=clean_port,
            username=user,
            rdns=rdns,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.proxy_type = ptype
        row.host = clean_host
        row.port = clean_port
        row.username = user
        row.rdns = rdns
        row.updated_at = now

    if clear_password:
        row.password_ciphertext = None
    elif password is not None and password != "":
        row.password_ciphertext = encrypt_value(password)
    elif not user:
        row.password_ciphertext = None

    row.last_status = "pending" if enabled else "disabled"
    row.last_error = None
    row.last_checked_at = now
    await db.commit()
    await db.refresh(row)
    return row


async def mark_proxy_status(account_id: int, status: str, error: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AccountProxy, account_id)
        if not row:
            return
        row.last_status = status[:32]
        row.last_error = (error or "")[:1000] or None
        row.last_checked_at = utcnow()
        await db.commit()
