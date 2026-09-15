from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import suppress
from typing import Any, AsyncIterator

from sqlalchemy import or_, select

from .audit import current_audit_context
from .db import AsyncSessionLocal
from .logging_config import redact_text
from .models import RealtimeEvent
from .tenant import current_tenant_id, tenant_scope
from .time_utils import utcnow

log = logging.getLogger("realtime_events")
LEVELS = {"debug", "info", "success", "warning", "error"}
QUEUE_SIZE = 512
HEARTBEAT_SECONDS = 15.0
_OVERFLOW = object()
_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|authorization|cookie|otp|2fa|api[_-]?hash|"
    r"session|cipher|encryption|private[_-]?key|ngrok|proxy[_-]?password",
    re.I,
)


def _sanitize(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key or ""):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)[:1000]
    if isinstance(value, dict):
        return {str(k)[:80]: _sanitize(v, str(k)) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v, key) for v in list(value)[:200]]
    return redact_text(str(value))[:1000]


def event_dict(row: RealtimeEvent) -> dict:
    return {
        "id": row.id,
        "feature": row.feature,
        "level": row.level,
        "phase": row.phase,
        "message": row.message,
        "job_id": row.job_id,
        "account_id": row.account_id,
        "correlation_id": row.correlation_id,
        "progress": row.progress or None,
        "metadata": row.metadata_json or None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class EventBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        async with self._lock:
            self._subs.setdefault(str(user_id), set()).add(q)
        return q

    async def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            group = self._subs.get(str(user_id))
            if not group:
                return
            group.discard(q)
            if not group:
                self._subs.pop(str(user_id), None)

    def publish(self, user_id: str, payload: dict) -> None:
        for q in list(self._subs.get(str(user_id), ())):
            if q.full():
                while not q.empty():
                    with suppress(asyncio.QueueEmpty):
                        q.get_nowait()
                with suppress(asyncio.QueueFull):
                    q.put_nowait(_OVERFLOW)
            with suppress(asyncio.QueueFull):
                q.put_nowait(payload)


broker = EventBroker()


async def emit_event(
    feature: str,
    level: str,
    phase: str,
    message: str,
    *,
    job_id: str | None = None,
    account_id: int | None = None,
    progress: dict | None = None,
    metadata: dict | None = None,
    correlation_id: str | None = None,
    user_id: str | None = None,
    strict: bool = False,
) -> dict | None:
    uid = str(user_id or current_tenant_id() or "").strip()
    if not uid:
        if strict:
            raise RuntimeError("Missing tenant context for realtime event")
        return None
    lvl = str(level or "info").lower().strip()
    if lvl not in LEVELS:
        lvl = "info"
    ctx = current_audit_context()
    corr = str(correlation_id or ctx.get("request_id") or uuid.uuid4().hex)[:64]
    try:
        with tenant_scope(uid):
            async with AsyncSessionLocal() as db:
                row = RealtimeEvent(
                    user_id=uid,
                    feature=str(feature or "system")[:48],
                    level=lvl,
                    phase=str(phase or "event")[:64],
                    message=redact_text(str(message or ""))[:4000],
                    job_id=str(job_id)[:64] if job_id else None,
                    account_id=int(account_id) if account_id is not None else None,
                    correlation_id=corr,
                    progress=_sanitize(progress or {}) or None,
                    metadata_json=_sanitize(metadata or {}) or None,
                    created_at=utcnow(),
                )
                db.add(row)
                await db.commit()
                await db.refresh(row)
        payload = event_dict(row)
        broker.publish(uid, payload)
        return payload
    except Exception as exc:
        log.warning("realtime event persist failed: %s", type(exc).__name__)
        if strict:
            raise
        return None


async def query_events(
    user_id: str,
    *,
    limit: int = 200,
    after_id: int | None = None,
    before_id: int | None = None,
    feature: str | None = None,
    level: str | None = None,
    job_id: str | None = None,
    account_id: int | None = None,
    search: str | None = None,
    ascending: bool = False,
) -> list[dict]:
    lim = max(1, min(500, int(limit)))
    with tenant_scope(user_id):
        async with AsyncSessionLocal() as db:
            q = select(RealtimeEvent)
            if after_id is not None:
                q = q.where(RealtimeEvent.id > int(after_id))
            if before_id is not None:
                q = q.where(RealtimeEvent.id < int(before_id))
            if feature:
                q = q.where(RealtimeEvent.feature == str(feature)[:48])
            if level:
                q = q.where(RealtimeEvent.level == str(level).lower()[:16])
            if job_id:
                q = q.where(RealtimeEvent.job_id == str(job_id)[:64])
            if account_id is not None:
                q = q.where(RealtimeEvent.account_id == int(account_id))
            if search:
                needle = f"%{str(search)[:100]}%"
                q = q.where(or_(RealtimeEvent.message.ilike(needle), RealtimeEvent.phase.ilike(needle)))
            order = RealtimeEvent.id.asc() if ascending else RealtimeEvent.id.desc()
            rows = (await db.execute(q.order_by(order).limit(lim))).scalars().all()
            return [event_dict(row) for row in rows]


def _matches(payload: dict, feature: str | None, level: str | None,
             job_id: str | None, account_id: int | None) -> bool:
    if feature and payload.get("feature") != feature:
        return False
    if level and payload.get("level") != level.lower():
        return False
    if job_id and payload.get("job_id") != job_id:
        return False
    if account_id is not None and payload.get("account_id") != int(account_id):
        return False
    return True


def _sse(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {payload['id']}\nevent: log\ndata: {data}\n\n"


async def _catch_up(user_id: str, cursor: int, **filters) -> AsyncIterator[tuple[int, str]]:
    while True:
        rows = await query_events(user_id, limit=500, after_id=cursor, ascending=True, **filters)
        if not rows:
            return
        for payload in rows:
            cursor = max(cursor, int(payload["id"]))
            yield cursor, _sse(payload)
        if len(rows) < 500:
            return


async def event_stream(
    user_id: str, *, after_id: int = 0, feature: str | None = None,
    level: str | None = None, job_id: str | None = None, account_id: int | None = None,
) -> AsyncIterator[str]:
    cursor = max(0, int(after_id or 0))
    filters = dict(feature=feature, level=level, job_id=job_id, account_id=account_id)
    q = await broker.subscribe(user_id)
    try:
        async for next_cursor, chunk in _catch_up(user_id, cursor, **filters):
            cursor = next_cursor
            yield chunk
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield f": heartbeat {int(utcnow().timestamp())}\n\n"
                continue
            if payload is _OVERFLOW:
                async for next_cursor, chunk in _catch_up(user_id, cursor, **filters):
                    cursor = next_cursor
                    yield chunk
                continue
            event_id = int(payload.get("id") or 0)
            if event_id <= cursor:
                continue
            cursor = event_id
            if _matches(payload, feature, level, job_id, account_id):
                yield _sse(payload)
    finally:
        await broker.unsubscribe(user_id, q)
