from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..realtime_events import event_stream, query_events
from ..tenant import current_tenant_id

router = APIRouter(prefix="/api/events", tags=["realtime-events"])


def _uid() -> str:
    uid = current_tenant_id()
    if not uid:
        raise HTTPException(401, "Chưa đăng nhập")
    return uid


@router.get("/history")
async def history(
    limit: int = Query(200, ge=1, le=500),
    after_id: int | None = Query(None, ge=0),
    before_id: int | None = Query(None, ge=1),
    feature: str | None = Query(None, max_length=48),
    level: str | None = Query(None, max_length=16),
    job_id: str | None = Query(None, max_length=64),
    account_id: int | None = None,
    q: str | None = Query(None, max_length=100),
):
    rows = await query_events(
        _uid(), limit=limit, after_id=after_id, before_id=before_id,
        feature=feature, level=level, job_id=job_id,
        account_id=account_id, search=q,
    )
    return {"items": rows, "next_before_id": rows[-1]["id"] if rows else None}


@router.get("/stream")
async def stream(
    request: Request,
    after_id: int | None = Query(None, ge=0),
    feature: str | None = Query(None, max_length=48),
    level: str | None = Query(None, max_length=16),
    job_id: str | None = Query(None, max_length=64),
    account_id: int | None = None,
):
    uid = _uid()
    header_cursor = (request.headers.get("last-event-id") or "").strip()
    cursor = int(after_id or 0)
    if header_cursor.isdigit():
        cursor = max(cursor, int(header_cursor))
    generator = event_stream(
        uid, after_id=cursor, feature=feature, level=level,
        job_id=job_id, account_id=account_id,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
