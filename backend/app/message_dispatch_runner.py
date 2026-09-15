from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from telethon.errors import FloodWaitError

from . import job_store, secrets_store
from .config import settings
from .db import AsyncSessionLocal
from .models import Account, BulkJob, MessageDispatchItem
from .runtime_settings import bulk_limits
from .tenant import system_scope, tenant_scope
from .tg_manager import manager
from .time_utils import utcnow
from .utils import friendly_error
from .realtime_events import emit_event

log = logging.getLogger("message_dispatch_runner")

RUNNABLE = {"queued", "rate_limited"}
TERMINAL = {"ok", "failed", "skipped", "cancelled", "in_flight_unknown"}


class TargetResolveError(ValueError):
    pass


async def _resolve_entity(cli, target: str):
    ref = target[1:] if target.startswith("@") else target
    if target.startswith("+"):
        ref = target
    elif ref.lstrip("-").isdigit():
        ref = int(ref)
    try:
        return await cli.get_entity(ref)
    except Exception as exc:
        raise TargetResolveError(f"Không thể tìm thấy người nhận {target}") from exc


def _secret_name(job_id: str) -> str:
    return f"job:message:{job_id}"


async def create_message_job(accounts, targets, text: str, parameters_extra: dict | None = None) -> str:
    job_id = uuid.uuid4().hex
    now = utcnow()
    from .tenant import require_tenant_id
    owner_id = require_tenant_id()
    await secrets_store.save_named_secret(_secret_name(job_id), text, owner_id)
    try:
        async with AsyncSessionLocal() as db:
            db.add(BulkJob(
                user_id=owner_id, id=job_id, type="message_multi_send", status="queued",
                parameters={"distribution": "round_robin", "target_count": len(targets),
                            "account_count": len(accounts), **(parameters_extra or {})},
                total=len(targets), success=0, failed=0, skipped=0, pending=len(targets),
                created_at=now, heartbeat_at=now, updated_at=now,
                checkpoint={"processed": 0, "total": len(targets)},
            ))
            await db.flush()
            for index, (target, key) in enumerate(targets):
                aid, _phone, _name = accounts[index % len(accounts)]
                db.add(MessageDispatchItem(
                    user_id=owner_id, job_id=job_id, account_id=aid,
                    target=target, normalized_target=key, status="queued",
                    attempts=0, max_attempts=3, updated_at=now,
                ))
            await db.commit()
        await emit_event("messaging", "info", "job_created", "Đã tạo tác vụ gửi tin nhắn", job_id=job_id, progress={"processed": 0, "total": len(targets)}, metadata={"target_count": len(targets), "account_count": len(accounts)}, user_id=owner_id)
    except Exception:
        await secrets_store.delete_named_secret(_secret_name(job_id), owner_id)
        raise
    return job_id


class MessageDispatchRunner:
    def __init__(self) -> None:
        self._loop_task: asyncio.Task | None = None
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._stop = asyncio.Event()
        self._global_sem: asyncio.Semaphore | None = None

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop.clear()
        self._global_sem = asyncio.Semaphore(max(1, min(50, int(settings.CONCURRENCY))))
        with system_scope():
            await self.recover_stale()
            self._loop_task = asyncio.create_task(self._loop(), name="message-dispatch-runner")

    async def stop(self) -> None:
        self._stop.set()
        tasks = list(self._job_tasks.values())
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._loop_task:
            with suppress(asyncio.CancelledError):
                await self._loop_task
        self._job_tasks.clear()
        self._loop_task = None
        self._global_sem = None

    async def recover_stale(self) -> None:
        now = utcnow()
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(MessageDispatchItem)
                .where(MessageDispatchItem.status == "processing")
                .values(status="in_flight_unknown", processing_token=None,
                        error_code="WORKER_INTERRUPTED",
                        detail="Worker dừng khi Telegram đang xử lý; không tự động gửi lại để tránh gửi trùng.",
                        finished_at=now, updated_at=now)
            )
            jobs = (await db.execute(select(BulkJob).where(
                BulkJob.type == "message_multi_send",
                BulkJob.status.in_(["running", "interrupted", "cancelling"]),
            ))).scalars().all()
            cancelled_secrets: list[tuple[str, str]] = []
            for job in jobs:
                if job.status == "cancelling":
                    await db.execute(
                        update(MessageDispatchItem)
                        .where(MessageDispatchItem.job_id == job.id,
                               MessageDispatchItem.status.notin_(TERMINAL))
                        .values(status="cancelled", processing_token=None, next_retry_at=None,
                                finished_at=now, updated_at=now)
                    )
                    job.status = "cancelled"
                    job.pending = 0
                    job.finished_at = now
                    cancelled_secrets.append((job.id, job.user_id))
                else:
                    job.status = "queued"
                    job.finished_at = None
                job.runner_id = None
                job.heartbeat_at = now
                job.updated_at = now
            await db.commit()
        for job_id, owner_id in cancelled_secrets:
            with suppress(Exception):
                await secrets_store.delete_named_secret(_secret_name(job_id), owner_id)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._start_available_jobs()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("message dispatch loop failed: %s", exc)
                await asyncio.sleep(3)

    async def _start_available_jobs(self) -> None:
        for job_id, task in list(self._job_tasks.items()):
            if task.done():
                with suppress(Exception):
                    await task
                self._job_tasks.pop(job_id, None)
        capacity = max(0, 4 - len(self._job_tasks))
        if capacity <= 0:
            return
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(
                select(BulkJob.id)
                .where(BulkJob.type == "message_multi_send", BulkJob.status == "queued")
                .order_by(BulkJob.created_at)
                .limit(capacity)
            )).scalars().all()
        for job_id in ids:
            if job_id not in self._job_tasks:
                self._job_tasks[job_id] = asyncio.create_task(
                    self._run_job(job_id), name=f"message-job-{job_id[:8]}"
                )

    async def _run_job(self, job_id: str) -> None:
        with system_scope():
            async with AsyncSessionLocal() as db:
                job = await db.get(BulkJob, job_id)
                owner_id = job.user_id if job else None
        if not owner_id:
            return
        with tenant_scope(owner_id):
            await self._run_job_scoped(job_id, owner_id)

    async def _run_job_scoped(self, job_id: str, owner_id: str) -> None:
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
            job.updated_at = now
            account_ids = list(dict.fromkeys((await db.execute(
                select(MessageDispatchItem.account_id)
                .where(MessageDispatchItem.job_id == job_id, MessageDispatchItem.account_id.is_not(None))
                .order_by(MessageDispatchItem.account_id)
            )).scalars().all()))
            await db.commit()
        await emit_event("messaging", "info", "worker_started", "Worker bắt đầu xử lý tác vụ gửi tin nhắn", job_id=job_id, progress={"processed": 0, "total": job.total}, metadata={"account_count": len(account_ids)}, user_id=owner_id)
        text = await secrets_store.get_named_secret(_secret_name(job_id), owner_id)
        if not text:
            await job_store.fail_job(job_id, "MESSAGE_SECRET_MISSING", "Không tìm thấy nội dung tin nhắn mã hóa để tiếp tục tác vụ.")
            return
        lo, hi, conc = await bulk_limits(owner_id)
        sem = asyncio.Semaphore(max(1, min(50, int(conc))))
        workers = [asyncio.create_task(
            self._run_account(job_id, int(aid), runner_id, text, sem, lo, hi)
        ) for aid in account_ids]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        finally:
            await self._finalize_job(job_id, runner_id, owner_id)

    async def _job_status(self, job_id: str, runner_id: str) -> str | None:
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job or job.runner_id != runner_id:
                return None
            now = utcnow()
            job.heartbeat_at = now
            job.updated_at = now
            await db.commit()
            return job.status

    async def _run_account(self, job_id: str, account_id: int, runner_id: str,
                           text: str, sem: asyncio.Semaphore, lo: float, hi: float) -> None:
        while not self._stop.is_set():
            status = await self._job_status(job_id, runner_id)
            if status in {None, "paused", "cancelling", "cancelled"}:
                return
            if status != "running":
                return
            cli = manager.get(account_id)
            if not cli:
                await asyncio.sleep(5)
                continue
            remaining = await manager.flood_wait_remaining(account_id)
            if remaining > 0:
                await asyncio.sleep(min(5, remaining))
                continue
            item = await self._claim_next(job_id, account_id)
            if item is None:
                if await self._has_unfinished(job_id, account_id):
                    await asyncio.sleep(1.5)
                    continue
                return
            await self._process_item(item, cli, account_id, text, sem)
            await self._refresh_counts(job_id)
            delay = random.uniform(max(0.0, lo), max(max(0.0, lo), hi))
            if delay > 0:
                await asyncio.sleep(delay)

    async def _claim_next(self, job_id: str, account_id: int) -> MessageDispatchItem | None:
        now = utcnow()
        async with AsyncSessionLocal() as db:
            item = (await db.execute(
                select(MessageDispatchItem)
                .where(
                    MessageDispatchItem.job_id == job_id,
                    MessageDispatchItem.account_id == account_id,
                    MessageDispatchItem.status.in_(RUNNABLE),
                    or_(MessageDispatchItem.next_retry_at.is_(None), MessageDispatchItem.next_retry_at <= now),
                )
                .order_by(MessageDispatchItem.id)
                .limit(1)
            )).scalar_one_or_none()
            if not item:
                return None
            item.status = "processing"
            item.processing_token = uuid.uuid4().hex
            item.attempts = (item.attempts or 0) + 1
            item.started_at = now
            item.next_retry_at = None
            item.updated_at = now
            await db.commit()
            return item

    async def _has_unfinished(self, job_id: str, account_id: int) -> bool:
        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count(MessageDispatchItem.id)).where(
                MessageDispatchItem.job_id == job_id,
                MessageDispatchItem.account_id == account_id,
                MessageDispatchItem.status.notin_(TERMINAL),
            )) or 0
            return bool(count)

    async def _process_item(self, item: MessageDispatchItem, cli, account_id: int,
                            text: str, sem: asyncio.Semaphore) -> None:
        token = item.processing_token
        timeout_s = max(0.1, float(getattr(settings, "TG_RPC_TIMEOUT_SECONDS", 45.0)))
        try:
            async with manager.account_operation(account_id, "message_multi_send"):
                async with sem:
                    global_sem = self._global_sem or asyncio.Semaphore(1)
                    async with global_sem:
                        entity = await asyncio.wait_for(_resolve_entity(cli, item.target), timeout=timeout_s)
                        await asyncio.wait_for(cli.send_message(entity, text), timeout=timeout_s)
            await manager.mark_operation_success(account_id)
            await self._save_item(item.id, token, "ok", "đã gửi")
        except asyncio.CancelledError:
            await self._save_item(
                item.id, token, "in_flight_unknown",
                "Worker dừng khi yêu cầu gửi đang chạy; không tự động gửi lại để tránh gửi trùng.",
                "WORKER_INTERRUPTED",
            )
            raise
        except FloodWaitError as exc:
            await manager.mark_flood_wait(account_id, exc.seconds)
            await self._save_rate_limited(item.id, token, exc.seconds, friendly_error(exc))
        except TargetResolveError as exc:
            await self._save_item(item.id, token, "failed", str(exc), "TargetResolveError")
        except asyncio.TimeoutError:
            await self._save_item(
                item.id, token, "in_flight_unknown",
                "Hết thời gian chờ Telegram; không tự động gửi lại vì trạng thái gửi chưa xác định.",
                "TimeoutError",
            )
        except Exception as exc:
            await manager.mark_operation_error(account_id, exc)
            await self._save_item(
                item.id, token, "in_flight_unknown", friendly_error(exc), type(exc).__name__
            )

    async def _save_item(self, item_id: int, token: str | None, status: str,
                         detail: str = "", error_code: str | None = None) -> None:
        now = utcnow(); payload = None
        async with AsyncSessionLocal() as db:
            item = await db.get(MessageDispatchItem, item_id)
            if not item or item.processing_token != token:
                return
            item.status = status; item.processing_token = None; item.error_code = error_code
            item.detail = detail[:2000] if detail else None
            item.finished_at = now if status in TERMINAL else None; item.updated_at = now
            payload = (item.user_id, item.job_id, item.account_id, item.target, item.attempts)
            await db.commit()
        owner_id, job_id, account_id, target, attempts = payload
        level = "success" if status == "ok" else "warning" if status in {"cancelled", "in_flight_unknown"} else "error" if status == "failed" else "info"
        await emit_event("messaging", level, status, f"Gửi tin: {status}", job_id=job_id, account_id=account_id, metadata={"target": target, "attempts": attempts, "error_code": error_code}, user_id=owner_id)

    async def _save_rate_limited(self, item_id: int, token: str | None,
                                 seconds: int, detail: str) -> None:
        now = utcnow(); payload = None; retry_at = now + timedelta(seconds=max(1, int(seconds or 1)))
        async with AsyncSessionLocal() as db:
            item = await db.get(MessageDispatchItem, item_id)
            if not item or item.processing_token != token:
                return
            item.status = "rate_limited"; item.processing_token = None; item.error_code = "FloodWaitError"
            item.detail = detail[:2000]; item.next_retry_at = retry_at; item.finished_at = None; item.updated_at = now
            payload = (item.user_id, item.job_id, item.account_id, item.target, item.attempts)
            await db.commit()
        owner_id, job_id, account_id, target, attempts = payload
        await emit_event("messaging", "warning", "flood_wait", f"Tin nhắn tạm chờ FloodWait {seconds}s", job_id=job_id, account_id=account_id, metadata={"target": target, "attempts": attempts, "retry_after_seconds": int(seconds), "next_retry_at": retry_at.isoformat()}, user_id=owner_id)

    async def _refresh_counts(self, job_id: str) -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(MessageDispatchItem.status, func.count(MessageDispatchItem.id))
                .where(MessageDispatchItem.job_id == job_id)
                .group_by(MessageDispatchItem.status)
            )).all()
            counts = {str(k): int(v) for k, v in rows}
            job = await db.get(BulkJob, job_id)
            if not job:
                return counts
            success = counts.get("ok", 0)
            failed = counts.get("failed", 0) + counts.get("in_flight_unknown", 0)
            skipped = counts.get("skipped", 0) + counts.get("cancelled", 0)
            pending = max(0, int(job.total or 0) - success - failed - skipped)
            now = utcnow()
            job.success = success
            job.failed = failed
            job.skipped = skipped
            job.pending = pending
            job.heartbeat_at = now
            job.updated_at = now
            job.checkpoint = {"processed": success + failed + skipped, "total": job.total,
                              "success": success, "failed": failed,
                              "skipped": skipped, "pending": pending}
            await db.commit()
            return counts

    async def _finalize_job(self, job_id: str, runner_id: str, owner_id: str) -> None:
        counts = await self._refresh_counts(job_id)
        now = utcnow()
        cleanup_secret = False
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job or job.runner_id != runner_id:
                return
            if job.status == "cancelling":
                await db.execute(
                    update(MessageDispatchItem)
                    .where(MessageDispatchItem.job_id == job_id,
                           MessageDispatchItem.status.notin_(TERMINAL))
                    .values(status="cancelled", processing_token=None,
                            next_retry_at=None, finished_at=now, updated_at=now)
                )
                job.status = "cancelled"
                job.finished_at = now
                cleanup_secret = True
            elif job.status == "paused":
                job.runner_id = None
            else:
                unfinished = sum(v for k, v in counts.items() if k not in TERMINAL)
                if unfinished == 0:
                    errors = counts.get("failed", 0) + counts.get("in_flight_unknown", 0)
                    job.status = "completed_with_errors" if errors else "completed"
                    job.finished_at = now
                    cleanup_secret = True
                else:
                    job.status = "queued"
                job.runner_id = None
            job.heartbeat_at = now
            job.updated_at = now
            event_status = job.status; event_progress = dict(job.checkpoint or {})
            await db.commit()
        if event_status in {"completed", "completed_with_errors", "cancelled", "failed"}:
            level = "success" if event_status == "completed" else "warning" if event_status in {"completed_with_errors", "cancelled"} else "error"
            await emit_event("messaging", level, "job_finished", f"Tác vụ gửi tin kết thúc: {event_status}", job_id=job_id, progress=event_progress, metadata={"status": event_status}, user_id=owner_id)
        elif event_status == "paused":
            await emit_event("messaging", "warning", "job_paused", "Tác vụ gửi tin đã tạm dừng", job_id=job_id, progress=event_progress, user_id=owner_id)
        if cleanup_secret:
            with suppress(Exception):
                await secrets_store.delete_named_secret(_secret_name(job_id), owner_id)


message_dispatch_runner = MessageDispatchRunner()


async def stream_message_job(job_id: str):
    """Stream SQL progress only; cancelling the HTTP stream never cancels the worker."""
    last_key = None
    while True:
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
            if not job:
                yield json.dumps({"type": "done", "job_id": job_id, "status": "missing"}) + "\n"
                return
            payload = {
                "type": "progress", "job_id": job.id, "status": job.status,
                "current": int(job.success or 0) + int(job.failed or 0) + int(job.skipped or 0),
                "total": int(job.total or 0), "success": int(job.success or 0),
                "failed": int(job.failed or 0), "skipped": int(job.skipped or 0),
                "pending": int(job.pending or 0), "checkpoint": job.checkpoint or {},
            }
            key = tuple(payload.get(k) for k in ("status", "current", "success", "failed", "skipped", "pending"))
            terminal = job.status in job_store.TERMINAL_JOB_STATUSES
        if key != last_key:
            yield json.dumps(payload, ensure_ascii=False) + "\n"
            last_key = key
        if terminal:
            payload["type"] = "done"
            yield json.dumps(payload, ensure_ascii=False) + "\n"
            return
        await asyncio.sleep(1.0)
