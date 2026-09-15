from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from .db import AsyncSessionLocal
from .models import Account, AccountProxy, AuditLog, BulkJob
from .tenant import current_tenant_id, system_scope

DEFAULT_QUOTAS = {
    "max_accounts": 50,
    "max_proxies": 50,
    "max_active_jobs": 3,
    "max_daily_messages": 5000,
    "max_daily_phone_checks": 10000,
}
_CACHE: dict[str, tuple[float, dict[str, int]]] = {}


def normalize_quotas(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    out = dict(DEFAULT_QUOTAS)
    for key in out:
        if key in raw:
            try:
                out[key] = max(0, min(1_000_000, int(raw[key])))
            except (TypeError, ValueError):
                pass
    return out

def clear_quota_cache(user_id: str | None = None) -> None:
    if user_id:
        _CACHE.pop(str(user_id), None)
    else:
        _CACHE.clear()


async def quotas_for_user(user_id: str) -> dict[str, int]:
    uid = str(user_id)
    cached = _CACHE.get(uid)
    if cached and cached[0] > time.monotonic():
        return dict(cached[1])
    from .supabase_identity import get_identity_user
    try:
        user = await asyncio.to_thread(get_identity_user, uid)
        quotas = normalize_quotas(user.quotas)
    except Exception:
        quotas = dict(DEFAULT_QUOTAS)
    _CACHE[uid] = (time.monotonic() + 30.0, quotas)
    return dict(quotas)


async def current_quotas() -> dict[str, int]:
    uid = current_tenant_id()
    if not uid:
        return dict(DEFAULT_QUOTAS)
    return await quotas_for_user(uid)


async def assert_account_capacity(additional: int = 1) -> None:
    uid = current_tenant_id()
    if not uid:
        return
    quotas = await quotas_for_user(uid)
    limit = quotas["max_accounts"]
    with system_scope():
        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count(Account.id)).where(
                Account.user_id == uid, Account.deleted_at.is_(None))) or 0
    if int(count) + max(0, additional) > limit:
        raise HTTPException(429, f"Đã đạt quota Telegram account ({limit})")

async def assert_proxy_capacity(account_id: int) -> None:
    uid = current_tenant_id()
    if not uid:
        return
    quotas = await quotas_for_user(uid)
    limit = quotas["max_proxies"]
    with system_scope():
        async with AsyncSessionLocal() as db:
            exists = await db.get(AccountProxy, account_id)
            if exists and str(exists.user_id) == uid:
                return
            count = await db.scalar(select(func.count(AccountProxy.account_id)).where(
                AccountProxy.user_id == uid)) or 0
    if int(count) >= limit:
        raise HTTPException(429, f"Đã đạt quota proxy ({limit})")


async def assert_job_capacity() -> None:
    uid = current_tenant_id()
    if not uid:
        return
    quotas = await quotas_for_user(uid)
    limit = quotas["max_active_jobs"]
    with system_scope():
        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.user_id == uid,
                BulkJob.status.in_(["queued", "running", "cancelling"]))) or 0
    if int(count) >= limit:
        raise HTTPException(429, f"Đã đạt quota job đang chạy ({limit})")


async def assert_daily_messages(additional: int = 1) -> None:
    uid = current_tenant_id()
    if not uid:
        return
    quotas = await quotas_for_user(uid)
    limit = quotas["max_daily_messages"]
    cutoff = __import__("app.time_utils", fromlist=["utcnow"]).utcnow() - timedelta(hours=24)
    with system_scope():
        async with AsyncSessionLocal() as db:
            bulk = await db.scalar(select(func.coalesce(func.sum(BulkJob.total), 0)).where(
                BulkJob.user_id == uid, BulkJob.created_at >= cutoff,
                BulkJob.type.in_(["message_send", "message_multi_send"]))) or 0
            direct = await db.scalar(select(func.count(AuditLog.id)).where(
                AuditLog.user_id == uid, AuditLog.created_at >= cutoff,
                AuditLog.action.in_(["message:send", "message:chat_send", "inbox:reply"]))) or 0
    if int(bulk) + int(direct) + max(0, additional) > limit:
        raise HTTPException(429, f"Đã đạt quota gửi tin nhắn 24 giờ ({limit})")


async def assert_daily_phone_checks(additional: int = 1) -> None:
    uid = current_tenant_id()
    if not uid:
        return
    quotas = await quotas_for_user(uid)
    limit = quotas["max_daily_phone_checks"]
    cutoff = __import__("app.time_utils", fromlist=["utcnow"]).utcnow() - timedelta(hours=24)
    with system_scope():
        async with AsyncSessionLocal() as db:
            used = await db.scalar(select(func.coalesce(func.sum(BulkJob.total), 0)).where(
                BulkJob.user_id == uid, BulkJob.created_at >= cutoff,
                BulkJob.type == "phone_check")) or 0
    if int(used) + max(0, additional) > limit:
        raise HTTPException(429, f"Đã đạt quota check số 24 giờ ({limit})")
