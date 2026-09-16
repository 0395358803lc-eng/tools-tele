from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_, select

from .models import BulkJob, PhoneCheckAccount, RealtimeEvent
from .time_utils import utcnow

_PHASE_KIND = {
    "created": "created", "job_created": "created",
    "queued": "queued", "worker_started": "running",
    "flood_wait": "flood_wait", "rate_limited": "flood_wait",
    "retry_required": "retry", "temporary_error": "retry",
    "account_waiting_retry": "retry", "waiting_retry": "retry",
    "paused": "paused", "job_paused": "paused",
    "resumed": "resume",
    "recovered": "recovery", "recovery": "recovery",
    "worker_interrupted": "recovery", "in_flight_unknown": "recovery",
    "finished": "completed", "job_finished": "completed",
    "failed": "failed", "cancel_requested": "cancelling",
}
_TIMELINE_PHASES = {
    "created", "job_created", "queued", "worker_started",
    "flood_wait", "rate_limited", "retry_required", "temporary_error",
    "paused", "job_paused", "resumed", "recovered", "recovery_interrupted",
    "worker_interrupted", "in_flight_unknown", "finished", "job_finished",
    "failed", "cancel_requested",
}


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _heartbeat_age(value) -> int | None:
    if value is None:
        return None
    now = utcnow()
    try:
        return max(0, int((now - value).total_seconds()))
    except TypeError:
        a = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        b = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        return max(0, int((b - a).total_seconds()))


def _sort_value(value):
    dt = _parse_dt(value)
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _event_kind(phase: str, metadata: dict | None) -> str:
    key = str(phase or "").lower()
    if key.startswith("account_flood_wait"):
        return "flood_wait"
    if key.startswith("account_waiting_retry"):
        return "retry"
    if key.startswith("recovery") or key.startswith("recovered"):
        return "recovery"
    kind = _PHASE_KIND.get(key, "event")
    if kind == "completed" and str((metadata or {}).get("status") or "").lower() == "failed":
        return "failed"
    return kind


def _timeline_row(event: RealtimeEvent) -> dict:
    metadata = dict(event.metadata_json or {})
    return {
        "id": event.id,
        "kind": _event_kind(event.phase, metadata),
        "feature": event.feature,
        "level": event.level,
        "phase": event.phase,
        "message": event.message,
        "account_id": event.account_id,
        "created_at": _iso(event.created_at),
        "progress": event.progress or None,
        "metadata": metadata or None,
    }


def _synthetic(kind: str, at, message: str, *, level: str = "info") -> dict:
    return {
        "id": None, "kind": kind, "feature": "jobs", "level": level,
        "phase": kind, "message": message, "account_id": None,
        "created_at": _iso(at), "progress": None, "metadata": {"synthetic": True},
    }


def _lane_status(counts: Counter, next_retry_at) -> str:
    if counts.get("processing") or counts.get("running"):
        return "running"
    if counts.get("rate_limited"):
        return "flood_wait"
    if counts.get("retry_required") or counts.get("temporary_error"):
        return "retry"
    if counts.get("queued") or counts.get("pending"):
        return "queued"
    if counts.get("failed") or counts.get("permanent_error") or counts.get("in_flight_unknown"):
        return "completed_with_errors"
    return "completed" if counts else "idle"


async def build_job_timeline(db, job: BulkJob, items: list[dict]) -> dict:
    event_rows = (await db.execute(
        select(RealtimeEvent)
        .where(RealtimeEvent.job_id == job.id, or_(
            RealtimeEvent.phase.in_(_TIMELINE_PHASES),
            RealtimeEvent.phase.like("account_%"),
        ))
        .order_by(RealtimeEvent.id.asc())
        .limit(500)
    )).scalars().all()
    timeline = [_timeline_row(row) for row in event_rows]
    seen = {row["kind"] for row in timeline}

    synthetic = []
    if "created" not in seen:
        synthetic.append(_synthetic("created", job.created_at, "Tác vụ được tạo"))
    if job.type in {"message_multi_send", "phone_check"} and "queued" not in seen:
        synthetic.append(_synthetic("queued", job.created_at, "Tác vụ vào hàng đợi"))
    if job.started_at and "running" not in seen:
        synthetic.append(_synthetic("running", job.started_at, "Worker bắt đầu xử lý"))
    if job.paused_at and "paused" not in seen:
        synthetic.append(_synthetic("paused", job.paused_at, "Tác vụ tạm dừng", level="warning"))
    terminal = str(job.status or "")
    if job.finished_at and not ({"completed", "failed"} & seen):
        kind = "failed" if terminal in {"failed", "interrupted"} else "completed"
        synthetic.append(_synthetic(kind, job.finished_at, f"Tác vụ kết thúc: {terminal}",
                                    level="error" if kind == "failed" else "success"))
    rank = {"created": 0, "queued": 1, "running": 2, "flood_wait": 3, "retry": 4,
            "paused": 5, "resume": 6, "recovery": 7, "completed": 8, "failed": 9}
    timeline.extend(synthetic)
    timeline.sort(key=lambda row: (_sort_value(row.get("created_at")),
                                   rank.get(row.get("kind"), 50), row.get("id") or 0))


    now = utcnow()
    by_account: dict[int | None, list[dict]] = defaultdict(list)
    for item in items:
        by_account[item.get("account_id")].append(item)

    phone_rows = []
    if job.type == "phone_check":
        phone_rows = (await db.execute(
            select(PhoneCheckAccount)
            .where(PhoneCheckAccount.job_id == job.id)
            .order_by(PhoneCheckAccount.id.asc())
        )).scalars().all()
    phone_by_account = {row.account_id: row for row in phone_rows}
    for account_id in phone_by_account:
        by_account.setdefault(account_id, [])

    account_events: dict[int, list[dict]] = defaultdict(list)
    for row in timeline:
        aid = row.get("account_id")
        if aid is not None:
            account_events[int(aid)].append(row)

    lanes = []
    all_retry_times = []
    for account_id, account_items in sorted(by_account.items(), key=lambda pair: (pair[0] is None, pair[0] or 0)):
        counts = Counter(str(item.get("status") or "unknown") for item in account_items)
        retry_times = [_parse_dt(item.get("next_retry_at")) for item in account_items if item.get("next_retry_at")]
        retry_times = [value for value in retry_times if value is not None]
        all_retry_times.extend(retry_times)
        current = next((item for item in account_items if item.get("status") in {"processing", "running"}), None)
        phone = phone_by_account.get(account_id)
        lane_status = phone.status if phone and phone.status else _lane_status(counts, min(retry_times) if retry_times else None)

        lanes.append({
            "account_id": account_id,
            "status": lane_status,
            "total": len(account_items),
            "processed": sum(counts.get(key, 0) for key in (
                "ok", "failed", "skipped", "cancelled", "in_flight_unknown",
                "found", "not_discoverable", "invalid", "permanent_error",
            )),
            "attempts": sum(int(item.get("attempts") or 0) for item in account_items),
            "status_counts": dict(counts),
            "current_item": None if current is None else {
                "id": current.get("id"), "target": current.get("target"),
                "status": current.get("status"), "attempts": current.get("attempts"),
            },
            "next_retry_at": _iso(min(retry_times)) if retry_times else None,
            "heartbeat_at": _iso(phone.heartbeat_at) if phone else None,
            "heartbeat_age_seconds": _heartbeat_age(phone.heartbeat_at) if phone else None,
            "phone_stats": None if not phone else {
                "assigned_total": phone.assigned_total, "processed": phone.processed,
                "found": phone.found, "not_discoverable": phone.not_discoverable,
                "errors": phone.errors,
            },
            "events": account_events.get(int(account_id), [])[-20:] if account_id is not None else [],
        })

    item_counts = Counter(str(item.get("status") or "unknown") for item in items)
    attempts_total = sum(int(item.get("attempts") or 0) for item in items)
    next_retry = min(all_retry_times) if all_retry_times else None

    retry_count = sum(1 for item in items if item.get("next_retry_at"))
    retry_seconds = None
    if next_retry is not None:
        try:
            retry_seconds = max(0, int((next_retry - now).total_seconds()))
        except TypeError:
            a = next_retry.replace(tzinfo=timezone.utc) if next_retry.tzinfo is None else next_retry
            b = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
            retry_seconds = max(0, int((a - b).total_seconds()))

    return {
        "timeline": timeline,
        "account_lanes": lanes,
        "item_statistics": {
            "total": len(items), "attempts": attempts_total,
            "status_counts": dict(item_counts),
        },
        "worker": {
            "runner_id": job.runner_id,
            "heartbeat_at": _iso(job.heartbeat_at),
            "heartbeat_age_seconds": _heartbeat_age(job.heartbeat_at),
            "stale": bool(job.heartbeat_at and (_heartbeat_age(job.heartbeat_at) or 0) > 180),
            "active": bool(job.runner_id and job.status == "running"),
        },
        "retry": {
            "waiting_items": retry_count,
            "next_retry_at": _iso(next_retry),
            "countdown_seconds": retry_seconds,
        },
    }
