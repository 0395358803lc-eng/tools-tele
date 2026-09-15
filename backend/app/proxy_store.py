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


def _slot_config(row: AccountProxy, slot: str) -> dict | None:
    slot = 'fallback' if slot == 'fallback' else 'primary'
    if slot == 'fallback':
        if not row.fallback_enabled or not row.fallback_host or not row.fallback_port:
            return None
        password = decrypt_value(row.fallback_password_ciphertext) if row.fallback_password_ciphertext else None
        return {
            'proxy_type': row.fallback_proxy_type or 'socks5', 'addr': row.fallback_host,
            'port': int(row.fallback_port), 'rdns': bool(row.fallback_rdns),
            'username': row.fallback_username or None, 'password': password, 'slot': 'fallback',
        }
    if not row.enabled:
        return None
    password = decrypt_value(row.password_ciphertext) if row.password_ciphertext else None
    return {
        'proxy_type': row.proxy_type, 'addr': row.host, 'port': int(row.port),
        'rdns': bool(row.rdns), 'username': row.username or None, 'password': password,
        'slot': 'primary',
    }


def public_proxy(row: AccountProxy | None) -> dict | None:
    if not row:
        return None
    fallback_ready = bool(row.fallback_enabled and row.fallback_host and row.fallback_port)
    return {
        'account_id': row.account_id, 'enabled': bool(row.enabled), 'proxy_type': row.proxy_type,
        'host': row.host, 'port': row.port, 'username': row.username or '',
        'has_password': bool(row.password_ciphertext), 'rdns': bool(row.rdns),
        'active_slot': row.active_slot or 'primary', 'failover_count': int(row.failover_count or 0),
        'last_failover_at': row.last_failover_at,
        'fallback': {
            'enabled': bool(row.fallback_enabled), 'ready': fallback_ready,
            'proxy_type': row.fallback_proxy_type or 'socks5', 'host': row.fallback_host or '',
            'port': row.fallback_port or 1080, 'username': row.fallback_username or '',
            'has_password': bool(row.fallback_password_ciphertext), 'rdns': bool(row.fallback_rdns),
        },
        'last_status': row.last_status or 'unknown', 'last_error': row.last_error or '',
        'last_checked_at': row.last_checked_at, 'updated_at': row.updated_at,
    }


def runtime_proxy_from_row(row: AccountProxy | None, slot: str | None = None) -> dict | None:
    if not row:
        return None
    chosen = slot or (row.active_slot or 'primary')
    cfg = _slot_config(row, chosen)
    if cfg is None and chosen == 'fallback':
        cfg = _slot_config(row, 'primary')
    return cfg


async def get_row(account_id: int, db: AsyncSession | None = None) -> AccountProxy | None:
    if db is not None:
        return await db.get(AccountProxy, account_id)
    async with AsyncSessionLocal() as own:
        return await own.get(AccountProxy, account_id)


async def runtime_proxy(account_id: int, slot: str | None = None) -> dict | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AccountProxy, account_id)
        return runtime_proxy_from_row(row, slot)


def has_fallback(row: AccountProxy | None) -> bool:
    return bool(row and row.fallback_enabled and row.fallback_host and row.fallback_port)


async def set_active_slot(account_id: int, slot: str, *, failover: bool = False) -> bool:
    slot = 'fallback' if slot == 'fallback' else 'primary'
    async with AsyncSessionLocal() as db:
        row = await db.get(AccountProxy, account_id)
        if not row:
            return False
        if slot == 'fallback' and not has_fallback(row):
            return False
        changed = (row.active_slot or 'primary') != slot
        row.active_slot = slot
        if changed and failover:
            row.failover_count = int(row.failover_count or 0) + 1
            row.last_failover_at = utcnow()
        row.updated_at = utcnow()
        await db.commit()
        return True


async def save_proxy(
    db: AsyncSession, account_id: int, *, enabled: bool, proxy_type: str, host: str,
    port: int, username: str | None, password: str | None, clear_password: bool, rdns: bool,
    fallback_enabled: bool = False, fallback_proxy_type: str = 'socks5', fallback_host: str = '',
    fallback_port: int = 1080, fallback_username: str | None = None,
    fallback_password: str | None = None, clear_fallback_password: bool = False,
    fallback_rdns: bool = True,
) -> AccountProxy:
    ptype, clean_host, clean_port = validate_proxy(proxy_type, host, port)
    user = (username or '').strip()[:255] or None
    fb_host = (fallback_host or '').strip()
    fb_user = (fallback_username or '').strip()[:255] or None
    fb_type = (fallback_proxy_type or 'socks5').strip().lower()
    fb_port = int(fallback_port or 1080)
    if fallback_enabled:
        fb_type, fb_host, fb_port = validate_proxy(fb_type, fb_host, fb_port)
    row = await db.get(AccountProxy, account_id)
    now = utcnow()
    if not row:
        row = AccountProxy(account_id=account_id, enabled=enabled, proxy_type=ptype,
            host=clean_host, port=clean_port, username=user, rdns=rdns,
            fallback_enabled=fallback_enabled, fallback_proxy_type=fb_type if fallback_enabled else None,
            fallback_host=fb_host or None, fallback_port=fb_port if fallback_enabled else None,
            fallback_username=fb_user, fallback_rdns=fallback_rdns, active_slot='primary',
            created_at=now, updated_at=now)
        db.add(row)
    else:
        row.enabled=enabled; row.proxy_type=ptype; row.host=clean_host; row.port=clean_port
        row.username=user; row.rdns=rdns; row.updated_at=now
        row.fallback_enabled=fallback_enabled
        row.fallback_proxy_type=fb_type if fallback_enabled else None
        row.fallback_host=fb_host or None; row.fallback_port=fb_port if fallback_enabled else None
        row.fallback_username=fb_user; row.fallback_rdns=fallback_rdns
        if not fallback_enabled and row.active_slot == 'fallback': row.active_slot='primary'
    if clear_password: row.password_ciphertext=None
    elif password: row.password_ciphertext=encrypt_value(password)
    elif not user: row.password_ciphertext=None
    if clear_fallback_password: row.fallback_password_ciphertext=None
    elif fallback_password: row.fallback_password_ciphertext=encrypt_value(fallback_password)
    elif not fb_user: row.fallback_password_ciphertext=None
    row.last_status='pending' if enabled else 'disabled'; row.last_error=None; row.last_checked_at=now
    await db.commit(); await db.refresh(row); return row


async def mark_proxy_status(account_id: int, status: str, error: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AccountProxy, account_id)
        if not row: return
        row.last_status=status[:32]; row.last_error=(error or '')[:1000] or None
        row.last_checked_at=utcnow(); await db.commit()
