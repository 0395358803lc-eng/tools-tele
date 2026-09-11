from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import job_store
from ..db import get_db
from ..models import Account, BulkJob, BulkJobItem
from ..audit import log_audit, _sanitize
from ..utils import bulk_stream, friendly_error

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

RETRYABLE_JOB_TYPES = {
    "group_join",
    "group_leave",
    "group_leave_target",
    "message_view",
    "terminate_other_sessions",
}
RETRY_ITEM_STATUSES = {"failed", "pending", "queued", "running"}


def _job_dict(job: BulkJob) -> dict:
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "parameters": _sanitize(job.parameters or {}) if job.parameters else None,
        "retry_supported": job.type in RETRYABLE_JOB_TYPES,
        "total": job.total,
        "success": job.success,
        "failed": job.failed,
        "skipped": job.skipped,
        "pending": job.pending,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@router.get("")
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(BulkJob).order_by(BulkJob.created_at.desc()).limit(limit)
    )
    return [_job_dict(job) for job in res.scalars().all()]


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    res = await db.execute(
        select(BulkJobItem)
        .where(BulkJobItem.job_id == job_id)
        .order_by(BulkJobItem.id)
    )
    items = [{
        "id": item.id,
        "account_id": item.account_id,
        "status": item.status,
        "attempts": item.attempts,
        "error_code": item.error_code,
        "error_detail": item.error_detail,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
    } for item in res.scalars().all()]
    out = _job_dict(job)
    out["items"] = items
    return out


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    accepted = await job_store.request_cancel(job_id)
    if accepted:
        await log_audit("job:cancel", detail={"job_id": job_id})
    return {"ok": accepted, "job_id": job_id, "status": "cancelling" if accepted else job.status}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    if job.status in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Không thể chạy lại tác vụ đang hoạt động")
    if job.type not in RETRYABLE_JOB_TYPES:
        raise HTTPException(400, "Loại tác vụ này không thể chạy lại an toàn")

    item_res = await db.execute(
        select(BulkJobItem)
        .where(BulkJobItem.job_id == job_id, BulkJobItem.status.in_(RETRY_ITEM_STATUSES))
        .order_by(BulkJobItem.id)
    )
    items = [item for item in item_res.scalars().all() if item.account_id is not None]
    if not items:
        raise HTTPException(409, "Không có tài khoản lỗi hoặc đang chờ để chạy lại")

    account_ids = [int(item.account_id) for item in items]
    acc_res = await db.execute(
        select(Account).where(Account.id.in_(account_ids), Account.deleted_at.is_(None))
    )
    by_id = {a.id: a for a in acc_res.scalars().all()}
    accounts = [
        (a.id, a.phone, (f"{a.first_name or ''} {a.last_name or ''}".strip() or a.phone))
        for aid in account_ids if (a := by_id.get(aid)) is not None
    ]
    if not accounts:
        raise HTTPException(409, "Không còn tài khoản nào có thể chạy lại")

    params = dict(job.parameters or {})
    params["retry_of"] = job_id
    action = None
    on_success = None

    if job.type == "group_join":
        target = str(params.get("target") or "").strip()
        if not target:
            raise HTTPException(409, "Tác vụ gốc thiếu dữ liệu cần thiết để chạy lại")
        from .groups import _join_handle, _cache
        action = lambda cli, aid: _join_handle(cli, target)
        on_success = lambda aid: _cache.pop(aid, None)

    elif job.type == "group_leave":
        try:
            chat_id = int(params.get("chat_id"))
        except (TypeError, ValueError):
            raise HTTPException(409, "Tác vụ gốc thiếu dữ liệu cần thiết để chạy lại")
        from .groups import _leave_with_client, _cache
        action = lambda cli, aid: _leave_with_client(cli, chat_id)
        on_success = lambda aid: _cache.pop(aid, None)

    elif job.type == "group_leave_target":
        target = str(params.get("target") or "").strip()
        if not target:
            raise HTTPException(409, "Tác vụ gốc thiếu dữ liệu cần thiết để chạy lại")
        from .groups import _leave_by_target_with_client, _cache
        action = lambda cli, aid: _leave_by_target_with_client(cli, target)
        on_success = lambda aid: _cache.pop(aid, None)

    elif job.type == "message_view":
        post_link = str(params.get("post_link") or "").strip()
        if not post_link:
            raise HTTPException(409, "Tác vụ gốc thiếu dữ liệu cần thiết để chạy lại")
        from .messaging import _parse_post_link
        from telethon.tl.functions.messages import GetMessagesViewsRequest
        try:
            chan, msg_id = _parse_post_link(post_link)
        except Exception as exc:
            raise HTTPException(400, friendly_error(exc))

        async def action(cli, aid):
            entity = await cli.get_entity(chan)
            result = await cli(GetMessagesViewsRequest(peer=entity, id=[msg_id], increment=True))
            count = result.views[0].views if (result and result.views) else None
            return "ok", (f"{count} lượt xem" if count is not None else "")

    elif job.type == "terminate_other_sessions":
        from .security import _terminate_other_authorizations

        async def action(cli, aid):
            killed, failed = await _terminate_other_authorizations(cli)
            detail = "không có phiên nào khác" if killed == 0 else f"đã chấm dứt {killed} phiên"
            if failed:
                detail += f", {failed} lỗi"
            return "ok", detail

    await log_audit("job:retry", detail={"source_job_id": job_id, "type": job.type, "accounts": len(accounts)})
    return StreamingResponse(
        bulk_stream(
            accounts, action, on_success=on_success,
            job_type=job.type, job_parameters=params,
        ),
        media_type="application/x-ndjson",
    )
