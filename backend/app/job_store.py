from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select

from .time_utils import utcnow
from .db import AsyncSessionLocal
from .models import AuditLog, BulkJob, BulkJobItem
from .audit import _sanitize

_cancel_events: dict[str, asyncio.Event] = {}
RUNNER_ID = uuid.uuid4().hex


async def create_job(
    job_type: str,
    accounts: list[tuple[int, str, str]],
    parameters: dict | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    now = utcnow()
    async with AsyncSessionLocal() as db:
        db.add(BulkJob(
            id=job_id,
            type=job_type[:64],
            status="running",
            parameters=_sanitize(parameters or {}) if parameters else None,
            total=len(accounts),
            success=0,
            failed=0,
            skipped=0,
            pending=0,
            created_at=now,
            started_at=now,
            runner_id=RUNNER_ID,
            heartbeat_at=now,
        ))
        for aid, _phone, _name in accounts:
            db.add(BulkJobItem(
                job_id=job_id,
                account_id=aid,
                status="queued",
                attempts=0,
            ))
        await db.commit()
    _cancel_events[job_id] = asyncio.Event()
    return job_id


async def _touch_job(db, job_id: str) -> None:
    job = await db.get(BulkJob, job_id)
    if job:
        job.heartbeat_at = utcnow()


async def mark_item_started(job_id: str, account_id: int) -> None:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(BulkJobItem).where(
            BulkJobItem.job_id == job_id,
            BulkJobItem.account_id == account_id,
        ))
        item = res.scalar_one_or_none()
        if item:
            item.status = "running"
            item.attempts = (item.attempts or 0) + 1
            item.started_at = utcnow()
            await _touch_job(db, job_id)
            await db.commit()


async def mark_item_result(
    job_id: str,
    account_id: int,
    status: str,
    detail: str = "",
    error_code: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(BulkJobItem).where(
            BulkJobItem.job_id == job_id,
            BulkJobItem.account_id == account_id,
        ))
        item = res.scalar_one_or_none()
        if item:
            item.status = status
            item.error_code = error_code
            item.error_detail = detail[:2000] if detail else None
            item.finished_at = utcnow()
            await _touch_job(db, job_id)
            await db.commit()


async def update_counts(
    job_id: str,
    *,
    success: int,
    failed: int,
    skipped: int,
    pending: int,
) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(BulkJob, job_id)
        if not job:
            return
        job.success = success
        job.failed = failed
        job.skipped = skipped
        job.pending = pending
        job.heartbeat_at = utcnow()
        await db.commit()


async def finish_job(
    job_id: str,
    status: str,
    *,
    success: int,
    failed: int,
    skipped: int,
    pending: int,
) -> None:
    now = utcnow()
    async with AsyncSessionLocal() as db:
        job = await db.get(BulkJob, job_id)
        if job:
            job.status = status
            job.success = success
            job.failed = failed
            job.skipped = skipped
            job.pending = pending
            job.finished_at = now
            job.heartbeat_at = now
            db.add(AuditLog(
                action=f"bulk:{job.type}"[:64],
                detail={
                    "job_id": job_id,
                    "status": status,
                    "total": job.total,
                    "success": success,
                    "failed": failed,
                    "skipped": skipped,
                    "pending": pending,
                },
                created_at=now,
            ))
            await db.commit()
    _cancel_events.pop(job_id, None)


async def request_cancel(job_id: str) -> bool:
    event = _cancel_events.get(job_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(BulkJob, job_id)
        if not job:
            return False
        if job.status in {"completed", "completed_with_errors", "cancelled", "failed", "interrupted"}:
            return False
        job.status = "cancelling"
        job.heartbeat_at = utcnow()
        await db.commit()
    if event:
        event.set()
    return True


async def is_cancelled(job_id: str) -> bool:
    event = _cancel_events.get(job_id)
    if event and event.is_set():
        return True
    async with AsyncSessionLocal() as db:
        job = await db.get(BulkJob, job_id)
        return bool(job and job.status in {"cancelling", "cancelled"})


async def recover_interrupted_jobs(stale_after_seconds: int = 180) -> int:
    """Mark only stale unfinished jobs as interrupted.

    Heartbeats prevent one app instance from declaring a job owned by another
    healthy instance interrupted during autoscale/startup overlap.
    """
    now = utcnow()
    cutoff = now - timedelta(seconds=max(30, stale_after_seconds))
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(BulkJob).where(
            BulkJob.status.in_(["queued", "running", "cancelling"]),
            or_(
                BulkJob.heartbeat_at < cutoff,
                and_(BulkJob.heartbeat_at.is_(None), BulkJob.started_at < cutoff),
                and_(BulkJob.heartbeat_at.is_(None), BulkJob.started_at.is_(None), BulkJob.created_at < cutoff),
            ),
        ))
        jobs = res.scalars().all()
        for job in jobs:
            job.status = "interrupted"
            job.finished_at = now
            job.heartbeat_at = now
        if jobs:
            await db.commit()
        return len(jobs)
