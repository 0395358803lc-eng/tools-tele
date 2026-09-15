from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import case, func, or_, select, update

from .db import AsyncSessionLocal
from .models import Account, BulkJob, PhoneCheckAccount, PhoneCheckItem
from .phone_checker import check_phone
from .tg_manager import manager
from .time_utils import utcnow
from .tenant import tenant_scope, system_scope
from .realtime_events import emit_event

log = logging.getLogger("phone_check_runner")

RUNNABLE_ITEM_STATUSES = {
    "queued", "retry_required", "temporary_error", "rate_limited", "in_flight_unknown",
}
TERMINAL_ITEM_STATUSES = {
    "found", "not_discoverable", "invalid", "permanent_error", "cancelled",
}


class PhoneCheckRunner:
    def __init__(self) -> None:
        self._loop_task: asyncio.Task | None = None
        self._job_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop.clear()
        await self.recover_stale()
        self._loop_task = asyncio.create_task(self._loop(), name="phone-check-runner")

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._job_task, self._loop_task):
            if task and not task.done():
                task.cancel()
        for task in (self._job_task, self._loop_task):
            if task:
                with suppress(asyncio.CancelledError):
                    await task
        self._job_task = None
        self._loop_task = None

    async def recover_stale(self) -> None:
        now = utcnow()
        recovery_at = now + timedelta(seconds=60)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(PhoneCheckItem)
                .where(PhoneCheckItem.status == "processing")
                .values(
                    status="in_flight_unknown",
                    processing_token=None,
                    next_retry_at=recovery_at,
                    error_code="WORKER_INTERRUPTED",
                    error_detail="Tác vụ bị gián đoạn khi yêu cầu Telegram đang chạy; chờ vùng an toàn trước khi thử lại.",
                    updated_at=now,
                )
            )
            jobs = (await db.execute(
                select(BulkJob).where(
                    BulkJob.type == "phone_check",
                    BulkJob.status.in_(["running", "interrupted", "cancelling"]),
                )
            )).scalars().all()
            for job in jobs:
                was_cancelling = job.status == "cancelling"
                job.status = "cancelled" if was_cancelling else "queued"
                job.runner_id = None
                job.heartbeat_at = now
                if was_cancelling:
                    job.finished_at = now
                    await db.execute(
                        update(PhoneCheckItem)
                        .where(PhoneCheckItem.job_id == job.id, PhoneCheckItem.status.notin_(TERMINAL_ITEM_STATUSES))
                        .values(status="cancelled", processing_token=None, next_retry_at=None, finished_at=now, updated_at=now)
                    )
                    job.pending = 0
            await db.commit()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._job_task is None or self._job_task.done():
                    if self._job_task is not None:
                        with suppress(Exception):
                            await self._job_task
                    job_id = await self._next_job_id()
                    self._job_task = asyncio.create_task(self._run_job(job_id)) if job_id else None
                await asyncio.sleep(1.5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("phone check loop failed: %s", exc)
                await asyncio.sleep(3)

    async def _next_job_id(self) -> str | None:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(BulkJob.id)
                .where(BulkJob.type == "phone_check", BulkJob.status == "queued")
                .order_by(BulkJob.created_at)
                .limit(1)
            )

    async def _run_job(self, job_id: str) -> None:
        with system_scope():
            async with AsyncSessionLocal() as lookup_db:
                lookup = await lookup_db.get(BulkJob, job_id)
                owner_id = lookup.user_id if lookup else None
        if not owner_id:
            return
        with tenant_scope(owner_id):
            await self._run_job_scoped(job_id)

    async def _run_job_scoped(self, job_id: str) -> None:
        runner_id = uuid.uuid4().hex
        now = utcnow()
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job or job.status != "queued":
                return
            job.status = "running"
            job.started_at = job.started_at or now
            job.runner_id = runner_id
            job.heartbeat_at = now
            accounts = (await db.execute(
                select(PhoneCheckAccount).where(PhoneCheckAccount.job_id == job_id).order_by(PhoneCheckAccount.id)
            )).scalars().all()
            for row in accounts:
                row.status = "running"
                row.heartbeat_at = now
            await db.commit()
            account_ids = [row.account_id for row in accounts if row.account_id is not None]
        await emit_event("phone_check", "info", "worker_started", "Worker bắt đầu tác vụ check số", job_id=job_id, progress={"processed": int(job.total or 0) - int(job.pending or 0), "total": int(job.total or 0)}, metadata={"account_count": len(account_ids)})

        workers = [asyncio.create_task(self._run_account(job_id, aid, runner_id)) for aid in account_ids]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        except Exception as exc:
            log.exception("phone check job %s failed: %s", job_id, exc)
        finally:
            await self._finalize_job(job_id, runner_id)

    async def _job_state(self, job_id: str, runner_id: str) -> tuple[str | None, dict]:
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job or job.runner_id != runner_id:
                return None, {}
            job.heartbeat_at = utcnow()
            await db.commit()
            return job.status, dict(job.parameters or {})

    async def _run_account(self, job_id: str, account_id: int, runner_id: str) -> None:
        while not self._stop.is_set():
            status, params = await self._job_state(job_id, runner_id)
            if status in (None, "paused", "cancelling", "cancelled"):
                await self._set_account_state(job_id, account_id, "paused" if status == "paused" else "stopped")
                return
            if status != "running":
                return

            cli = manager.get(account_id)
            if not cli:
                await self._set_account_state(job_id, account_id, "waiting_connection")
                await asyncio.sleep(5)
                continue

            remaining = await manager.flood_wait_remaining(account_id)
            if remaining > 0:
                await self._set_account_state(job_id, account_id, "flood_wait")
                await asyncio.sleep(min(5, remaining))
                continue

            item = await self._claim_next_item(job_id, account_id)
            if item is None:
                if await self._account_has_unfinished(job_id, account_id):
                    await self._set_account_state(job_id, account_id, "waiting_retry")
                    await asyncio.sleep(2)
                    continue
                await self._set_account_state(job_id, account_id, "completed")
                return

            token = item.processing_token
            try:
                timeout_s = max(5.0, min(120.0, float(params.get("rpc_timeout", 45.0))))
                async with manager.account_operation(account_id, "phone_check"):
                    result = await asyncio.wait_for(
                        check_phone(cli, item.normalized_phone or item.original_phone, item.id),
                        timeout=timeout_s,
                    )
            except asyncio.CancelledError:
                await self._quarantine_item(item.id, token)
                raise
            except asyncio.TimeoutError:
                await self._save_retry(item.id, token, "temporary_error", "TimeoutError", "Yêu cầu Telegram hết thời gian chờ.")
            except Exception as exc:
                await self._save_retry(item.id, token, "temporary_error", type(exc).__name__, str(exc)[:500])
            else:
                if result.status == "rate_limited":
                    await manager.mark_flood_wait(account_id, result.retry_after_seconds or 60)
                await self._save_result(item.id, token, result)

            interval = max(0.1, min(60.0, float(params.get("min_request_interval", 1.2))))
            await asyncio.sleep(interval)

    async def _claim_next_item(self, job_id: str, account_id: int) -> PhoneCheckItem | None:
        now = utcnow()
        async with AsyncSessionLocal() as db:
            item = (await db.execute(
                select(PhoneCheckItem)
                .where(
                    PhoneCheckItem.job_id == job_id,
                    PhoneCheckItem.account_id == account_id,
                    PhoneCheckItem.status.in_(RUNNABLE_ITEM_STATUSES),
                    or_(PhoneCheckItem.next_retry_at.is_(None), PhoneCheckItem.next_retry_at <= now),
                )
                .order_by(PhoneCheckItem.id)
                .limit(1)
            )).scalar_one_or_none()
            if not item:
                return None
            token = uuid.uuid4().hex
            item.status = "processing"
            item.processing_token = token
            item.attempts = (item.attempts or 0) + 1
            item.started_at = now
            item.next_retry_at = None
            item.updated_at = now
            await db.commit()
            return item

    async def _quarantine_item(self, item_id: int, token: str | None) -> None:
        now = utcnow()
        async with AsyncSessionLocal() as db:
            item = await db.get(PhoneCheckItem, item_id)
            if not item or item.processing_token != token:
                return
            item.status = "in_flight_unknown"
            item.processing_token = None
            item.next_retry_at = now + timedelta(seconds=60)
            item.error_code = "WORKER_INTERRUPTED"
            item.error_detail = "Worker dừng khi yêu cầu Telegram đang chạy; chờ vùng an toàn trước khi thử lại."
            item.updated_at = now
            await db.commit()

    async def _save_result(self, item_id: int, token: str | None, result) -> None:
        """Persist one checker result and update progress counters atomically.

        The previous implementation re-scanned/grouped the entire job after every
        item, which made large jobs approach O(N^2). Counters are now updated in
        the same SQL transaction as the item transition; finalization still uses
        SQL as the source of truth for terminal-state checks.
        """
        now = utcnow()
        async with AsyncSessionLocal() as db:
            item = await db.get(PhoneCheckItem, item_id)
            if not item or item.processing_token != token:
                return
            if result.status in {"retry_required", "temporary_error", "rate_limited"}:
                delay = result.retry_after_seconds or min(3600, 30 * (2 ** max(0, item.attempts - 1)))
                if item.attempts >= item.max_attempts and result.status != "rate_limited":
                    item.status = "permanent_error"
                    item.error_code = "RETRY_EXHAUSTED"
                    item.error_detail = result.error_detail or "Đã hết số lần thử cho phép"
                    item.finished_at = now
                else:
                    item.status = result.status
                    item.next_retry_at = now + timedelta(seconds=max(1, int(delay)))
                    item.error_code = result.error_code
                    item.error_detail = (result.error_detail or "")[:2000] or None
            else:
                item.status = result.status
                item.telegram_user_id = result.telegram_user_id
                item.username = result.username
                item.first_name = result.first_name
                item.last_name = result.last_name
                item.presence = result.presence
                item.last_online_at = result.last_online_at
                item.cleanup_error = result.cleanup_error
                item.error_code = result.error_code
                item.error_detail = (result.error_detail or "")[:2000] or None
                item.checked_at = now
                item.finished_at = now
            item.processing_token = None
            item.updated_at = now

            terminal = item.status in TERMINAL_ITEM_STATUSES
            if terminal and item.account_id is not None:
                acc_values = {
                    "processed": PhoneCheckAccount.processed + 1,
                    "heartbeat_at": now,
                    "updated_at": now,
                }
                if item.status == "found":
                    acc_values["found"] = PhoneCheckAccount.found + 1
                elif item.status == "not_discoverable":
                    acc_values["not_discoverable"] = PhoneCheckAccount.not_discoverable + 1
                elif item.status in {"invalid", "permanent_error"}:
                    acc_values["errors"] = PhoneCheckAccount.errors + 1
                await db.execute(
                    update(PhoneCheckAccount)
                    .where(
                        PhoneCheckAccount.job_id == item.job_id,
                        PhoneCheckAccount.account_id == item.account_id,
                    )
                    .values(**acc_values)
                )

            if terminal:
                job_values = {
                    "pending": case((BulkJob.pending > 0, BulkJob.pending - 1), else_=0),
                    "heartbeat_at": now,
                }
                if item.status == "found":
                    job_values["success"] = BulkJob.success + 1
                elif item.status == "not_discoverable":
                    job_values["skipped"] = BulkJob.skipped + 1
                elif item.status == "permanent_error":
                    job_values["failed"] = BulkJob.failed + 1
                await db.execute(
                    update(BulkJob).where(BulkJob.id == item.job_id).values(**job_values)
                )
            event_payload = (item.user_id, item.job_id, item.account_id, item.status, item.attempts, item.error_code, item.next_retry_at)
            await db.commit()
        owner_id, event_job_id, event_account_id, event_status, attempts, error_code, retry_at = event_payload
        level = "success" if event_status == "found" else "error" if event_status in {"invalid", "permanent_error"} else "warning" if event_status in {"retry_required", "temporary_error", "rate_limited"} else "info"
        await emit_event("phone_check", level, event_status, f"Check số: {event_status}", job_id=event_job_id, account_id=event_account_id, metadata={"item_id": item_id, "attempts": attempts, "error_code": error_code, "next_retry_at": retry_at.isoformat() if retry_at else None}, user_id=owner_id)

    async def _save_retry(self, item_id: int, token: str | None, status: str, code: str, detail: str) -> None:
        class R:
            pass
        result = R()
        result.status = status
        result.retry_after_seconds = None
        result.error_code = code
        result.error_detail = detail
        result.telegram_user_id = result.username = result.first_name = result.last_name = None
        result.presence = result.last_online_at = result.cleanup_error = None
        await self._save_result(item_id, token, result)

    async def _account_has_unfinished(self, job_id: str, account_id: int) -> bool:
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count(PhoneCheckItem.id)).where(
                    PhoneCheckItem.job_id == job_id,
                    PhoneCheckItem.account_id == account_id,
                    PhoneCheckItem.status.notin_(TERMINAL_ITEM_STATUSES),
                )
            )
            return bool(count)

    async def _set_account_state(self, job_id: str, account_id: int, status: str) -> None:
        changed = False; owner_id = None; previous = None
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(PhoneCheckAccount).where(
                PhoneCheckAccount.job_id == job_id, PhoneCheckAccount.account_id == account_id
            ))).scalar_one_or_none()
            if row:
                owner_id, previous = row.user_id, row.status; changed = previous != status
                row.status = status; row.heartbeat_at = utcnow(); await db.commit()
        if changed:
            level = "success" if status == "completed" else "warning" if status in {"flood_wait", "waiting_retry", "waiting_connection", "paused"} else "info"
            await emit_event("phone_check", level, f"account_{status}", f"Account check số: {status}", job_id=job_id, account_id=account_id, metadata={"previous_status": previous, "status": status}, user_id=owner_id)

    async def _finalize_job(self, job_id: str, runner_id: str) -> None:
        now = utcnow()
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job or job.runner_id != runner_id:
                return
            if job.status == "cancelling":
                await db.execute(
                    update(PhoneCheckItem)
                    .where(PhoneCheckItem.job_id == job_id, PhoneCheckItem.status.notin_(TERMINAL_ITEM_STATUSES))
                    .values(status="cancelled", processing_token=None, finished_at=now, updated_at=now)
                )
                job.status = "cancelled"
                job.pending = 0
                job.finished_at = now
            elif job.status == "paused":
                pass
            else:
                unfinished = await db.scalar(select(func.count(PhoneCheckItem.id)).where(
                    PhoneCheckItem.job_id == job_id, PhoneCheckItem.status.notin_(TERMINAL_ITEM_STATUSES)
                )) or 0
                if unfinished == 0:
                    errors = await db.scalar(select(func.count(PhoneCheckItem.id)).where(
                        PhoneCheckItem.job_id == job_id,
                        PhoneCheckItem.status.in_(["invalid", "permanent_error"]),
                    )) or 0
                    job.status = "completed_with_errors" if errors else "completed"
                    job.finished_at = now
                else:
                    job.status = "queued"
            job.runner_id = None
            job.heartbeat_at = now
            event_status = job.status; owner_id = job.user_id
            progress = {"processed": int(job.total or 0) - int(job.pending or 0), "total": int(job.total or 0), "success": int(job.success or 0), "failed": int(job.failed or 0), "skipped": int(job.skipped or 0), "pending": int(job.pending or 0)}
            await db.commit()
        if event_status in {"completed", "completed_with_errors", "cancelled"}:
            level = "success" if event_status == "completed" else "warning"
            await emit_event("phone_check", level, "job_finished", f"Tác vụ check số kết thúc: {event_status}", job_id=job_id, progress=progress, metadata={"status": event_status}, user_id=owner_id)
        elif event_status == "paused":
            await emit_event("phone_check", "warning", "job_paused", "Tác vụ check số đã tạm dừng", job_id=job_id, progress=progress, user_id=owner_id)


phone_check_runner = PhoneCheckRunner()
