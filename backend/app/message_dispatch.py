from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from telethon.errors import FloodWaitError

from . import job_store
from .config import settings
from .db import AsyncSessionLocal
from .models import BulkJob, MessageDispatchItem
from .tg_manager import manager
from .time_utils import utcnow
from .utils import BulkPacer, friendly_error

_PHONE_RE = re.compile(r"^\+[\d\s().-]{6,}$")
_NUMERIC_RE = re.compile(r"^-?\d+$")


class TargetResolveError(ValueError):
    pass


def _phone_normalize(value: str) -> str:
    return "+" + "".join(ch for ch in value if ch.isdigit())


def normalize_message_target(raw: str) -> tuple[str, str]:
    """Return (display_target, dedupe_key) without importing unknown contacts."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("Mục tiêu đang trống")
    if len(value) > 255:
        raise ValueError("Mục tiêu dài quá 255 ký tự")

    if _PHONE_RE.fullmatch(value):
        phone = _phone_normalize(value)
        if len(phone) < 8 or len(phone) > 17:
            raise ValueError(f"Số điện thoại không hợp lệ: {value}")
        return phone, f"phone:{phone}"

    if value.lower().startswith("tg://resolve"):
        query = parse_qs(urlparse(value).query)
        domain = (query.get("domain") or [""])[0].strip()
        if not domain:
            raise ValueError("Liên kết tg:// không hợp lệ")
        return f"@{domain}", f"user:{domain.lower()}"

    body = value
    for prefix in ("https://", "http://"):
        if body.lower().startswith(prefix):
            body = body[len(prefix):]
            break
    low = body.lower()
    if low.startswith("t.me/") or low.startswith("telegram.me/"):
        rest = body.split("/", 1)[1]
        if rest.startswith("+") or rest.lower().startswith("joinchat/"):
            raise ValueError("Liên kết mời nhóm/kênh không phải người nhận tin nhắn trực tiếp")
        path = rest.partition("?")[0].strip("/")
        peer = path.split("/")[0].strip()
        if not peer:
            raise ValueError("Liên kết t.me không hợp lệ")
        return f"@{peer}", f"user:{peer.lower()}"

    if value.startswith("@"):
        peer = value[1:].strip()
        if not peer:
            raise ValueError("Tên người dùng đang trống")
        return f"@{peer}", f"user:{peer.lower()}"

    if _NUMERIC_RE.fullmatch(value):
        return value, f"id:{value}"

    return f"@{value}", f"user:{value.lower()}"


def normalize_message_targets(values: list[str], *, max_targets: int = 200) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        if not (raw or "").strip():
            continue
        display, key = normalize_message_target(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append((display, key))
        if len(unique) > max_targets:
            raise ValueError(f"Tối đa {max_targets} người nhận cho mỗi tác vụ")
    if not unique:
        raise ValueError("Chưa có người nhận hợp lệ")
    return unique


async def _resolve_entity(cli, target: str):
    if target.startswith("+"):
        try:
            return await cli.get_entity(target)
        except Exception as exc:
            raise TargetResolveError(
                f"Không thể tìm thấy {target} từ tài khoản này. "
                "Số điện thoại phải là người dùng Telegram mà tài khoản có thể nhận diện."
            ) from exc
    ref = target[1:] if target.startswith("@") else target
    if _NUMERIC_RE.fullmatch(ref):
        ref = int(ref)
    try:
        return await cli.get_entity(ref)
    except Exception as exc:
        raise TargetResolveError(f"Không thể tìm thấy người nhận {target}") from exc


async def _create_job(
    accounts: list[tuple[int, str, str]],
    targets: list[tuple[str, str]],
) -> tuple[str, list[dict]]:
    job_id = uuid.uuid4().hex
    now = utcnow()
    assignments: list[dict] = []
    async with AsyncSessionLocal() as db:
        db.add(BulkJob(
            id=job_id,
            type="message_multi_send",
            status="running",
            parameters={
                "distribution": "round_robin",
                "target_count": len(targets),
                "account_count": len(accounts),
            },
            total=len(targets), success=0, failed=0, skipped=0, pending=0,
            created_at=now, started_at=now,
            runner_id=job_store.RUNNER_ID, heartbeat_at=now,
        ))
        await db.flush()
        for index, (target, key) in enumerate(targets):
            aid, phone, name = accounts[index % len(accounts)]
            item = MessageDispatchItem(
                job_id=job_id,
                account_id=aid,
                target=target,
                normalized_target=key,
                status="queued",
                attempts=0,
            )
            db.add(item)
            await db.flush()
            assignments.append({
                "item_id": item.id, "account_id": aid,
                "phone": phone, "account_name": name,
                "target": target, "key": key,
            })
        await db.commit()
    return job_id, assignments


async def _mark_started(item_id: int) -> None:
    async with AsyncSessionLocal() as db:
        item = await db.get(MessageDispatchItem, item_id)
        if item:
            item.status = "running"
            item.attempts = (item.attempts or 0) + 1
            item.started_at = utcnow()
            job = await db.get(BulkJob, item.job_id)
            if job:
                job.heartbeat_at = utcnow()
            await db.commit()


async def _mark_result(item_id: int, status: str, detail: str = "", error_code: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        item = await db.get(MessageDispatchItem, item_id)
        if item:
            item.status = status
            item.detail = detail[:2000] if detail else None
            item.error_code = error_code
            item.finished_at = utcnow()
            job = await db.get(BulkJob, item.job_id)
            if job:
                job.heartbeat_at = utcnow()
            await db.commit()


async def eligible_message_accounts(accounts: list[tuple[int, str, str]]) -> tuple[list[tuple[int, str, str]], list[dict]]:
    eligible: list[tuple[int, str, str]] = []
    excluded: list[dict] = []
    for aid, phone, name in accounts:
        cli = manager.get(aid)
        if not cli:
            excluded.append({"id": aid, "name": name, "reason": "chưa kết nối"})
            continue
        remaining = await manager.flood_wait_remaining(aid)
        if remaining > 0:
            excluded.append({"id": aid, "name": name, "reason": f"FloodWait còn khoảng {remaining} giây"})
            continue
        eligible.append((aid, phone, name))
    return eligible, excluded


async def multi_target_message_stream(
    accounts: list[tuple[int, str, str]],
    targets: list[tuple[str, str]],
    text: str,
):
    """Send each unique target once, distributed across accounts, with SQL progress."""
    job_id, assignments = await _create_job(accounts, targets)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for item in assignments:
        grouped[item["account_id"]].append(item)

    conc = max(1, min(50, int(getattr(settings, "CONCURRENCY", 8) or 8)))
    sem = asyncio.Semaphore(conc)
    pacer = BulkPacer()
    out_q: asyncio.Queue = asyncio.Queue()
    timeout_s = max(0.1, float(getattr(settings, "TG_RPC_TIMEOUT_SECONDS", 45.0)))

    async def finish(item: dict, status: str, detail: str, error_code: str | None = None):
        await _mark_result(item["item_id"], status, detail, error_code)
        await out_q.put({**item, "status": status, "detail": detail, "error_code": error_code})

    async def worker(aid: int, rows: list[dict]):
        cli = manager.get(aid)
        for item in rows:
            if await job_store.is_cancelled(job_id):
                await finish(item, "skipped", "đã hủy trước khi gửi", "cancelled")
                continue
            if not cli:
                await finish(item, "skipped", "tài khoản không còn kết nối", "not_connected")
                continue
            remaining = await manager.flood_wait_remaining(aid)
            if remaining > 0:
                await finish(item, "pending", f"FloodWait còn khoảng {remaining} giây", "FloodWaitError")
                continue

            await pacer.wait_turn()
            if await job_store.is_cancelled(job_id):
                await finish(item, "skipped", "đã hủy trước khi gửi", "cancelled")
                continue

            await _mark_started(item["item_id"])
            try:
                async with manager.account_operation(aid, "message_multi_send"):
                    async with sem:
                        entity = await asyncio.wait_for(_resolve_entity(cli, item["target"]), timeout=timeout_s)
                        await asyncio.wait_for(cli.send_message(entity, text), timeout=timeout_s)
                await manager.mark_operation_success(aid)
                await finish(item, "ok", "đã gửi")
            except asyncio.TimeoutError as exc:
                await manager.mark_operation_error(aid, exc)
                await finish(
                    item, "failed",
                    "Hết thời gian chờ Telegram; trạng thái gửi có thể chưa xác định, không tự động gửi lại.",
                    "TimeoutError",
                )
            except FloodWaitError as exc:
                await manager.mark_flood_wait(aid, exc.seconds)
                await finish(item, "pending", friendly_error(exc), type(exc).__name__)
            except TargetResolveError as exc:
                await finish(item, "failed", str(exc), "TargetResolveError")
            except Exception as exc:
                await manager.mark_operation_error(aid, exc)
                await finish(item, "failed", friendly_error(exc), type(exc).__name__)

    tasks = [asyncio.create_task(worker(aid, rows)) for aid, rows in grouped.items()]
    total = len(assignments)
    success = failed = skipped = pending = 0
    results: list[dict] = []
    try:
        for current in range(1, total + 1):
            row = await out_q.get()
            status = row["status"]
            if status == "ok": success += 1
            elif status == "failed": failed += 1
            elif status == "pending": pending += 1
            else: skipped += 1
            results.append(row)
            await job_store.update_counts(
                job_id, success=success, failed=failed, skipped=skipped, pending=pending,
            )
            yield json.dumps({
                "type": "progress", "job_id": job_id,
                "current": current, "total": total,
                "account_name": f"{row['account_name']} → {row['target']}",
                "status": status, "detail": row["detail"],
                "success": success, "failed": failed,
                "skipped": skipped, "pending": pending,
            }, ensure_ascii=False) + "\n"
    except BaseException:
        await job_store.request_cancel(job_id)
        raise
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)

    cancelled = await job_store.is_cancelled(job_id)
    final_status = "cancelled" if cancelled else (
        "completed_with_errors" if failed or pending else "completed"
    )
    await job_store.finish_job(
        job_id, final_status,
        success=success, failed=failed, skipped=skipped, pending=pending,
    )
    yield json.dumps({
        "type": "done", "job_id": job_id, "status": final_status,
        "total": total, "success": success, "failed": failed,
        "skipped": skipped, "pending": pending,
        "results": [
            {"account_id": r["account_id"], "target": r["target"], "status": r["status"], "detail": r["detail"]}
            for r in results
        ],
    }, ensure_ascii=False) + "\n"
