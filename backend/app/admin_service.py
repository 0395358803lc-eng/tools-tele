from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select

from .audit import _sanitize
from .config import settings
from .db import AsyncSessionLocal
from .models import (
    Account, AccountProxy, AccountStatusHistory, AppSetting, AuditLog, BulkJob, BulkJobItem,
    EncryptedSecret, GoneAccount, MessageDispatchItem, PhoneCheckAccount, PhoneCheckItem,
    SecurityMessage, TargetCheck, TargetCheckResult, TelegramSession,
)
from .system_status import operational_status, readiness
from .ops_alerts import current_alerts, recent_alerts, reconcile
from .tenant import system_scope, tenant_scope
from .tg_manager import manager


def _dt(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _job_dict(job: BulkJob) -> dict:
    return {
        "id": job.id, "user_id": job.user_id, "type": job.type,
        "status": job.status, "parameters": _sanitize(job.parameters or {}),
        "total": job.total, "success": job.success, "failed": job.failed,
        "skipped": job.skipped, "pending": job.pending,
        "created_at": _dt(job.created_at), "started_at": _dt(job.started_at),
        "finished_at": _dt(job.finished_at), "heartbeat_at": _dt(job.heartbeat_at),
        "retry_supported": job.type in {"group_join", "group_leave", "group_leave_target", "message_view", "terminate_other_sessions"},
    }

async def tenant_usage(user_id: str) -> dict:
    with system_scope():
        async with AsyncSessionLocal() as db:
            account_total = await db.scalar(select(func.count(Account.id)).where(
                Account.user_id == user_id, Account.deleted_at.is_(None))) or 0
            connected = await db.scalar(select(func.count(Account.id)).where(
                Account.user_id == user_id, Account.deleted_at.is_(None),
                Account.status == "connected")) or 0
            proxy_total = await db.scalar(select(func.count(AccountProxy.account_id)).where(
                AccountProxy.user_id == user_id)) or 0
            session_total = await db.scalar(select(func.count(TelegramSession.id)).where(
                TelegramSession.user_id == user_id)) or 0
            job_total = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.user_id == user_id)) or 0
            active_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.user_id == user_id,
                BulkJob.status.in_(["queued", "running", "cancelling"]))) or 0
            failed_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.user_id == user_id,
                BulkJob.status.in_(["failed", "completed_with_errors", "interrupted"]))) or 0
            messages = await db.scalar(select(func.count(MessageDispatchItem.id)).where(
                MessageDispatchItem.user_id == user_id)) or 0
            phone_checks = await db.scalar(select(func.count(PhoneCheckItem.id)).where(
                PhoneCheckItem.user_id == user_id)) or 0
            security_messages = await db.scalar(select(func.count(SecurityMessage.id)).where(
                SecurityMessage.user_id == user_id)) or 0

    return {
        "accounts": int(account_total), "connected_accounts": int(connected),
        "proxies": int(proxy_total), "telegram_sessions": int(session_total),
        "jobs": int(job_total), "active_jobs": int(active_jobs),
        "failed_jobs": int(failed_jobs), "message_items": int(messages),
        "phone_check_items": int(phone_checks),
        "security_messages": int(security_messages),
    }


async def dashboard_counts() -> dict:
    with system_scope():
        async with AsyncSessionLocal() as db:
            accounts = await db.scalar(select(func.count(Account.id)).where(
                Account.deleted_at.is_(None))) or 0
            connected = await db.scalar(select(func.count(Account.id)).where(
                Account.deleted_at.is_(None), Account.status == "connected")) or 0
            proxies = await db.scalar(select(func.count(AccountProxy.account_id))) or 0
            jobs = await db.scalar(select(func.count(BulkJob.id))) or 0
            active_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.status.in_(["queued", "running", "cancelling"]))) or 0
            failed_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
                BulkJob.status.in_(["failed", "completed_with_errors", "interrupted"]))) or 0
            message_items = await db.scalar(select(func.count(MessageDispatchItem.id))) or 0
            phone_items = await db.scalar(select(func.count(PhoneCheckItem.id))) or 0
    return {
        "accounts": int(accounts), "connected_accounts": int(connected),
        "proxies": int(proxies), "jobs": int(jobs), "active_jobs": int(active_jobs),
        "failed_jobs": int(failed_jobs), "message_items": int(message_items),
        "phone_check_items": int(phone_items),
    }

async def admin_jobs(*, limit: int = 100, user_id: str | None = None,
                     status: str | None = None, job_type: str | None = None) -> list[dict]:
    with system_scope():
        async with AsyncSessionLocal() as db:
            q = select(BulkJob).order_by(BulkJob.created_at.desc()).limit(limit)
            if user_id:
                q = q.where(BulkJob.user_id == user_id)
            if status:
                q = q.where(BulkJob.status == status)
            if job_type:
                q = q.where(BulkJob.type == job_type)
            rows = (await db.execute(q)).scalars().all()
    return [_job_dict(row) for row in rows]


async def admin_audit(*, limit: int = 100, offset: int = 0,
                      user_id: str | None = None, action: str | None = None,
                      account_id: int | None = None) -> list[dict]:
    with system_scope():
        async with AsyncSessionLocal() as db:
            q = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
            if user_id:
                q = q.where(AuditLog.user_id == user_id)
            if action:
                q = q.where(AuditLog.action == action)
            if account_id is not None:
                q = q.where(AuditLog.account_id == account_id)
            rows = (await db.execute(q)).scalars().all()
    return [{
        "id": r.id, "user_id": r.user_id, "action": r.action,
        "account_id": r.account_id, "detail": _sanitize(r.detail or {}),
        "created_at": _dt(r.created_at),
    } for r in rows]

async def admin_health() -> dict:
    with system_scope():
        ready = await readiness()
        status = await operational_status()
    public_url = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
    tunnel = {"configured": bool(public_url), "ok": False, "status_code": None}
    if public_url:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(public_url + "/api/health/live")
            tunnel.update({"ok": resp.status_code == 200, "status_code": resp.status_code})
        except Exception:
            pass
    backups = Path(__file__).resolve().parents[2] / "backups"
    files = sorted(backups.rglob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True) if backups.exists() else []
    latest_backup = None
    if files:
        p = files[0]
        latest_backup = {
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        }
    alerts = []
    if not ready.get("ok"):
        alerts.append({"level": "critical", "code": "readiness", "message": "Readiness đang lỗi"})
    if int(status.get("stale_jobs") or 0) > 0:
        alerts.append({"level": "warning", "code": "stale_jobs", "message": "Có job bị treo/stale"})
    if public_url and not tunnel["ok"]:
        alerts.append({"level": "critical", "code": "ngrok", "message": "Domain public không phản hồi"})
    if latest_backup is None:
        alerts.append({"level": "warning", "code": "backup", "message": "Chưa tìm thấy backup runtime"})
    else:
        backup_age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(latest_backup["modified_at"])).total_seconds() / 3600
        latest_backup["age_hours"] = round(max(0.0, backup_age_h), 1)
        if backup_age_h > 36:
            alerts.append({"level": "warning", "code": "backup_stale", "message": "Backup gần nhất đã quá 36 giờ"})
    if float(status.get("system_cpu_percent") or 0) >= 95:
        alerts.append({"level": "warning", "code": "cpu", "message": "CPU hệ thống đang trên 95%"})
    if float(status.get("system_memory_percent") or 0) >= 90:
        alerts.append({"level": "warning", "code": "memory", "message": "RAM hệ thống đang trên 90%"})
    if float(status.get("event_loop_lag_ms") or 0) >= 250:
        alerts.append({"level": "warning", "code": "event_loop", "message": "Event loop lag đang cao"})
    reconcile(alerts, source="health")
    maintenance_status = None
    status_file = Path(__file__).resolve().parents[2] / "logs" / "maintenance-status.json"
    try:
        raw = json.loads(status_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            maintenance_status = raw
    except Exception:
        pass
    return {"readiness": ready, "runtime": status, "tunnel": tunnel,
            "latest_backup": latest_backup, "alerts": alerts,
            "active_alerts": current_alerts(), "recent_alerts": recent_alerts(30),
            "maintenance": maintenance_status}


async def purge_tenant_data(user_id: str) -> dict[str, int]:
    uid = str(user_id)
    with system_scope():
        async with AsyncSessionLocal() as db:
            accounts = (await db.execute(select(Account).where(Account.user_id == uid))).scalars().all()
    with tenant_scope(uid):
        for account in accounts:
            try:
                await manager.remove_account_instance(account, delete_session_file=True)
            except Exception:
                pass
    order = [
        TargetCheckResult, MessageDispatchItem, PhoneCheckItem, PhoneCheckAccount, BulkJobItem,
        SecurityMessage, TelegramSession, AccountStatusHistory, AccountProxy, AuditLog,
        TargetCheck, BulkJob, GoneAccount, AppSetting, EncryptedSecret, Account,
    ]
    counts: dict[str, int] = {}
    with system_scope():
        async with AsyncSessionLocal() as db:
            for model in order:
                result = await db.execute(delete(model).where(model.user_id == uid))
                counts[model.__tablename__] = max(0, int(result.rowcount or 0))
            await db.commit()
    shutil.rmtree(settings.sessions_path / f"user_{uid}", ignore_errors=True)
    return counts
