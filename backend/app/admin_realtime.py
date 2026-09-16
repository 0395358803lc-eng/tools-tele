from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from .audit import _sanitize
from .db import AsyncSessionLocal
from .logging_config import redact_text
from .models import (
    Account, AccountProxy, BulkJob, MessageDispatchItem, PhoneCheckItem, RealtimeEvent,
)
from .tenant import system_scope
from .time_utils import utcnow

ACTIVE_JOB_STATUSES = ("queued", "running", "cancelling", "paused")
FAILED_JOB_STATUSES = ("failed", "completed_with_errors", "interrupted")
PROXY_FAILURE_STATUSES = ("failed", "error", "timeout", "unreachable")


def _dt(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _safe_event(row: RealtimeEvent) -> dict:
    return {
        "id": row.id, "user_id": row.user_id, "feature": row.feature,
        "level": row.level, "phase": row.phase, "message": redact_text(str(row.message or ""))[:4000],
        "job_id": row.job_id, "account_id": row.account_id,
        "correlation_id": row.correlation_id,
        "progress": _sanitize(row.progress or {}) or None,
        "metadata": _sanitize(row.metadata_json or {}) or None,
        "created_at": _dt(row.created_at),
    }


async def realtime_snapshot() -> dict:
    now = utcnow()
    one_minute = now - timedelta(minutes=1)
    five_minutes = now - timedelta(minutes=5)
    with system_scope():
        async with AsyncSessionLocal() as db:
            connected = await db.scalar(select(func.count(Account.id)).where(
                Account.deleted_at.is_(None), Account.status == "connected")) or 0
            flood_wait = await db.scalar(select(func.count(Account.id)).where(
                Account.deleted_at.is_(None), Account.flood_wait_until.is_not(None),
                Account.flood_wait_until > now)) or 0
            proxy_failures = await db.scalar(select(func.count(AccountProxy.account_id)).where(
                AccountProxy.last_status.in_(PROXY_FAILURE_STATUSES))) or 0
            active_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.status.in_(ACTIVE_JOB_STATUSES))) or 0
            failed_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.status.in_(FAILED_JOB_STATUSES))) or 0
            queue_depth = await db.scalar(select(func.coalesce(func.sum(BulkJob.pending), 0)).where(
                BulkJob.status.in_(ACTIVE_JOB_STATUSES))) or 0
            event_rate = await db.scalar(select(func.count(RealtimeEvent.id)).where(
                RealtimeEvent.created_at >= one_minute)) or 0
            recent_errors = (await db.execute(select(RealtimeEvent).where(
                RealtimeEvent.level.in_(("warning", "error"))).order_by(
                RealtimeEvent.id.desc()).limit(20))).scalars().all()
            recent_users = set((await db.execute(select(RealtimeEvent.user_id).where(
                RealtimeEvent.created_at >= five_minutes).distinct())).scalars().all())
            async def grouped(model_col, *conditions):
                q = select(model_col, func.count()).where(*conditions).group_by(model_col)
                return {str(uid): int(count) for uid, count in (await db.execute(q)).all()}
            connected_by_user = await grouped(Account.user_id, Account.deleted_at.is_(None), Account.status == "connected")
            flood_by_user = await grouped(Account.user_id, Account.deleted_at.is_(None),
                Account.flood_wait_until.is_not(None), Account.flood_wait_until > now)
            active_jobs_by_user = await grouped(BulkJob.user_id, BulkJob.status.in_(ACTIVE_JOB_STATUSES))
            failed_jobs_by_user = await grouped(BulkJob.user_id, BulkJob.status.in_(FAILED_JOB_STATUSES))
            proxy_fail_by_user = await grouped(AccountProxy.user_id, AccountProxy.last_status.in_(PROXY_FAILURE_STATUSES))
            active_user_ids = sorted({str(x) for x in recent_users if x} | set(connected_by_user) | set(active_jobs_by_user))
            users = [{
                "user_id": uid, "connected_accounts": connected_by_user.get(uid, 0),
                "flood_wait": flood_by_user.get(uid, 0), "active_jobs": active_jobs_by_user.get(uid, 0),
                "failed_jobs": failed_jobs_by_user.get(uid, 0), "proxy_failures": proxy_fail_by_user.get(uid, 0),
            } for uid in active_user_ids]
            message_queue = await db.scalar(select(func.count(MessageDispatchItem.id)).where(
                MessageDispatchItem.status.in_(("queued", "processing", "rate_limited", "temporary_error")))) or 0
            phone_queue = await db.scalar(select(func.count(PhoneCheckItem.id)).where(
                PhoneCheckItem.status.in_(("queued", "processing", "retry_wait", "rate_limited")))) or 0
    return {
        "active_users": len(active_user_ids), "connected_accounts": int(connected),
        "flood_wait": int(flood_wait), "proxy_failures": int(proxy_failures),
        "active_jobs": int(active_jobs), "failed_jobs": int(failed_jobs),
        "queue_depth": int(queue_depth), "message_queue_depth": int(message_queue),
        "phone_queue_depth": int(phone_queue), "event_rate_per_min": int(event_rate),
        "users": users, "recent_errors": [_safe_event(row) for row in recent_errors],
        "generated_at": _dt(now),
    }


async def realtime_events(*, limit: int = 200, before_id: int | None = None,
                          user_id: str | None = None, feature: str | None = None,
                          level: str | None = None, account_id: int | None = None,
                          job_id: str | None = None) -> list[dict]:
    lim = max(1, min(500, int(limit)))
    with system_scope():
        async with AsyncSessionLocal() as db:
            q = select(RealtimeEvent)
            if before_id is not None: q = q.where(RealtimeEvent.id < int(before_id))
            if user_id: q = q.where(RealtimeEvent.user_id == str(user_id))
            if feature: q = q.where(RealtimeEvent.feature == str(feature)[:48])
            if level: q = q.where(RealtimeEvent.level == str(level).lower()[:16])
            if account_id is not None: q = q.where(RealtimeEvent.account_id == int(account_id))
            if job_id: q = q.where(RealtimeEvent.job_id == str(job_id)[:64])
            rows = (await db.execute(q.order_by(RealtimeEvent.id.desc()).limit(lim))).scalars().all()
    return [_safe_event(row) for row in rows]


async def realtime_user_detail(user_id: str) -> dict:
    uid = str(user_id)
    now = utcnow()
    with system_scope():
        async with AsyncSessionLocal() as db:
            accounts = (await db.execute(select(Account).where(
                Account.user_id == uid, Account.deleted_at.is_(None)).order_by(Account.id.asc()))).scalars().all()
            proxies = (await db.execute(select(AccountProxy).where(AccountProxy.user_id == uid))).scalars().all()
            proxy_map = {row.account_id: row for row in proxies}
            jobs = (await db.execute(select(BulkJob).where(BulkJob.user_id == uid).order_by(
                BulkJob.created_at.desc()).limit(50))).scalars().all()
    safe_accounts = []
    for account in accounts:
        proxy = proxy_map.get(account.id)
        safe_accounts.append({
            "id": account.id, "phone": account.phone, "username": account.username,
            "first_name": account.first_name, "status": account.status,
            "flood_wait_until": _dt(account.flood_wait_until),
            "in_flood_wait": bool(account.flood_wait_until and account.flood_wait_until > now),
            "last_success_at": _dt(account.last_success_at), "last_ping_at": _dt(account.last_ping_at),
            "last_error_type": account.last_error_type, "reconnect_count": account.reconnect_count,
            "proxy": None if not proxy else {
                "enabled": proxy.enabled, "active_slot": proxy.active_slot,
                "last_status": proxy.last_status, "last_checked_at": _dt(proxy.last_checked_at),
                "failover_count": proxy.failover_count,
            },
        })
    safe_jobs = [{
        "id": job.id, "type": job.type, "status": job.status, "total": job.total,
        "success": job.success, "failed": job.failed, "skipped": job.skipped,
        "pending": job.pending, "created_at": _dt(job.created_at),
        "started_at": _dt(job.started_at), "finished_at": _dt(job.finished_at),
        "heartbeat_at": _dt(job.heartbeat_at), "last_error_code": job.last_error_code,
    } for job in jobs]
    return {"user_id": uid, "accounts": safe_accounts, "jobs": safe_jobs}
