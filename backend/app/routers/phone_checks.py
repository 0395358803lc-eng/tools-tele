from __future__ import annotations

import csv
import io
import json
import uuid
from collections import Counter
from typing import Literal
from openpyxl import Workbook

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log_audit
from ..db import get_db
from ..models import Account, AccountProxy, BulkJob, PhoneCheckAccount, PhoneCheckItem
from ..phone_checker import normalize_phone_list
from ..phone_import import parse_phone_file
from ..quota import assert_daily_phone_checks, assert_job_capacity
from ..tg_manager import manager
from ..time_utils import utcnow
from ..utils import read_upload_limited

router = APIRouter(prefix="/api/phone-checks", tags=["phone-checks"])
ACTIVE_JOB_STATUSES = {"queued", "running", "paused", "cancelling"}
TERMINAL_ITEM_STATUSES = {"found", "not_discoverable", "invalid", "permanent_error", "cancelled"}


class PreviewIn(BaseModel):
    phones: list[str] = Field(default_factory=list, max_length=50000)
    phone_region: str = Field(default="VN", min_length=2, max_length=3)


class CreatePhoneCheckIn(PreviewIn):
    account_ids: list[int] = Field(min_length=1, max_length=50)
    name: str = Field(default="Kiểm tra số Telegram", min_length=1, max_length=120)
    max_attempts: int = Field(default=3, ge=1, le=10)
    min_request_interval: float = Field(default=1.2, ge=0.1, le=60.0)


def _job_dict(job: BulkJob) -> dict:
    return {
        "id": job.id,
        "name": (job.parameters or {}).get("name") or "Kiểm tra số Telegram",
        "type": job.type,
        "status": job.status,
        "total": job.total,
        "found": job.success,
        "errors": job.failed,
        "other_terminal": job.skipped,
        "pending": job.pending,
        "parameters": job.parameters or {},
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _item_dict(row: PhoneCheckItem) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "original_phone": row.original_phone,
        "normalized_phone": row.normalized_phone,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "next_retry_at": row.next_retry_at,
        "telegram_user_id": row.telegram_user_id,
        "username": row.username,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "presence": row.presence,
        "last_online_at": row.last_online_at,
        "error_code": row.error_code,
        "error_detail": row.error_detail,
        "cleanup_error": row.cleanup_error,
        "checked_at": row.checked_at,
    }



def _item_filters(job_id: str, status: str | None = None, q: str | None = None, account_id: int | None = None):
    clauses = [PhoneCheckItem.job_id == job_id]
    if status:
        clauses.append(PhoneCheckItem.status == status)
    if account_id:
        clauses.append(PhoneCheckItem.account_id == account_id)
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        clauses.append(or_(
            PhoneCheckItem.original_phone.ilike(like),
            PhoneCheckItem.normalized_phone.ilike(like),
            PhoneCheckItem.username.ilike(like),
            PhoneCheckItem.first_name.ilike(like),
            PhoneCheckItem.last_name.ilike(like),
        ))
    return clauses


@router.post("/preview")
async def preview_numbers(body: PreviewIn):
    rows, summary = normalize_phone_list(body.phones, body.phone_region)
    return {"summary": summary, "phones": [row["original"] for row in rows]}


@router.post("/import")
async def import_numbers(
    file: UploadFile = File(...),
    phone_region: str = Form("VN"),
):
    try:
        raw = await read_upload_limited(file, 5 * 1024 * 1024)
        phones = parse_phone_file(file.filename or "", raw)
        rows, summary = normalize_phone_list(phones, phone_region)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"filename": file.filename, "summary": summary, "phones": [row["original"] for row in rows]}


@router.post("/jobs")
async def create_phone_check_job(body: CreatePhoneCheckIn, db: AsyncSession = Depends(get_db)):
    rows, summary = normalize_phone_list(body.phones, body.phone_region)
    if not rows:
        raise HTTPException(400, "Không có số điện thoại để kiểm tra")

    account_ids = list(dict.fromkeys(body.account_ids))
    accs = (await db.execute(
        select(Account).where(Account.id.in_(account_ids), Account.deleted_at.is_(None))
    )).scalars().all()
    by_id = {row.id: row for row in accs}
    ordered = [by_id.get(aid) for aid in account_ids]
    if any(acc is None for acc in ordered):
        raise HTTPException(404, "Một hoặc nhiều tài khoản không còn tồn tại")
    unavailable = [acc for acc in ordered if acc.status != "connected" or manager.get(acc.id) is None]
    if unavailable:
        raise HTTPException(409, "Tất cả tài khoản được chọn phải đang kết nối")

    busy_ids = set((await db.execute(
        select(PhoneCheckAccount.account_id)
        .join(BulkJob, BulkJob.id == PhoneCheckAccount.job_id)
        .where(
            PhoneCheckAccount.account_id.in_(account_ids),
            BulkJob.type == "phone_check",
            BulkJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )).scalars().all())
    if busy_ids:
        raise HTTPException(409, f"Có {len(busy_ids)} tài khoản đang thuộc tác vụ check số khác")

    valid_rows = [row for row in rows if row["normalized"]]
    await assert_job_capacity()
    await assert_daily_phone_checks(len(valid_rows))
    active_accounts = ordered[: min(len(ordered), len(valid_rows))]
    if valid_rows and not active_accounts:
        raise HTTPException(409, "Không có tài khoản khả dụng để kiểm tra")

    job_id = uuid.uuid4().hex
    now = utcnow()
    params = {
        "name": body.name.strip(),
        "phone_region": body.phone_region.upper(),
        "max_attempts": body.max_attempts,
        "min_request_interval": body.min_request_interval,
        "rpc_timeout": 45.0,
        "account_count": len(active_accounts),
        "valid_count": summary["valid"],
        "invalid_count": summary["invalid"],
        "duplicate_count": summary["duplicates"],
    }
    db.add(BulkJob(
        id=job_id,
        type="phone_check",
        status="queued",
        parameters=params,
        total=len(rows),
        success=0,
        failed=0,
        skipped=summary["invalid"],
        pending=summary["valid"],
        created_at=now,
        heartbeat_at=now,
    ))
    await db.flush()

    assigned_counts: Counter[int] = Counter()
    valid_index = 0
    for row in rows:
        normalized = row["normalized"]
        account_id = None
        status = "invalid"
        error_code = "INVALID_PHONE"
        error_detail = "Số điện thoại không thể chuẩn hóa theo E.164."
        finished_at = now
        if normalized:
            account_id = active_accounts[valid_index % len(active_accounts)].id
            valid_index += 1
            assigned_counts[account_id] += 1
            status = "queued"
            error_code = None
            error_detail = None
            finished_at = None
        db.add(PhoneCheckItem(
            job_id=job_id,
            account_id=account_id,
            original_phone=row["original"][:64],
            normalized_phone=normalized,
            dedupe_key=normalized or f"invalid:{row['original'][:100]}",
            status=status,
            attempts=0,
            max_attempts=body.max_attempts,
            error_code=error_code,
            error_detail=error_detail,
            finished_at=finished_at,
            created_at=now,
            updated_at=now,
        ))

    for acc in active_accounts:
        db.add(PhoneCheckAccount(
            job_id=job_id,
            account_id=acc.id,
            status="queued",
            assigned_total=assigned_counts[acc.id],
            processed=0,
            found=0,
            not_discoverable=0,
            errors=0,
            created_at=now,
            updated_at=now,
        ))
    await db.commit()
    await log_audit("phone_check:create", detail={
        "job_id": job_id,
        "accounts": len(active_accounts),
        "total": len(rows),
        "valid": summary["valid"],
        "invalid": summary["invalid"],
        "duplicates": summary["duplicates"],
    })
    return {"job_id": job_id, "summary": summary, "distribution": dict(assigned_counts)}


@router.get("/jobs")
async def list_phone_check_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    jobs = (await db.execute(
        select(BulkJob)
        .where(BulkJob.type == "phone_check")
        .order_by(BulkJob.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [_job_dict(job) for job in jobs]


@router.get("/jobs/{job_id}")
async def phone_check_job_detail(
    job_id: str,
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    account_id: int | None = Query(None, ge=1),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    clauses = _item_filters(job_id, status, q, account_id)
    query = select(PhoneCheckItem).where(*clauses)
    filtered_total = int(await db.scalar(select(func.count(PhoneCheckItem.id)).where(*clauses)) or 0)
    items = (await db.execute(query.order_by(PhoneCheckItem.id).offset(offset).limit(limit))).scalars().all()
    count_rows = (await db.execute(
        select(PhoneCheckItem.status, func.count(PhoneCheckItem.id))
        .where(PhoneCheckItem.job_id == job_id)
        .group_by(PhoneCheckItem.status)
    )).all()
    account_rows = (await db.execute(
        select(PhoneCheckAccount, Account, AccountProxy)
        .outerjoin(Account, Account.id == PhoneCheckAccount.account_id)
        .outerjoin(AccountProxy, AccountProxy.account_id == PhoneCheckAccount.account_id)
        .where(PhoneCheckAccount.job_id == job_id)
        .order_by(PhoneCheckAccount.id)
    )).all()
    return {
        **_job_dict(job),
        "counts": {key: int(value) for key, value in count_rows},
        "accounts": [{
            "account_id": row.account_id,
            "name": (f"{acc.first_name or ''} {acc.last_name or ''}".strip() if acc else "") or (acc.phone if acc else "Tài khoản đã xóa"),
            "phone": acc.phone if acc else "",
            "status": row.status,
            "telegram_status": acc.status if acc else "deleted",
            "flood_wait_until": acc.flood_wait_until if acc else None,
            "operation_owner": manager.operation_owner(row.account_id) if row.account_id else None,
            "proxy": {
                "enabled": bool(proxy and proxy.enabled),
                "type": proxy.proxy_type if proxy else None,
                "status": proxy.last_status if proxy else None,
            },
            "assigned_total": row.assigned_total,
            "processed": row.processed,
            "found": row.found,
            "not_discoverable": row.not_discoverable,
            "errors": row.errors,
            "heartbeat_at": row.heartbeat_at,
        } for row, acc, proxy in account_rows],
        "items": [_item_dict(row) for row in items],
        "filtered_total": filtered_total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < filtered_total,
    }


@router.post("/jobs/{job_id}/pause")
async def pause_phone_check_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    if job.status not in {"queued", "running"}:
        raise HTTPException(409, "Tác vụ hiện không thể tạm dừng")
    job.status = "paused"
    job.heartbeat_at = utcnow()
    await db.commit()
    await log_audit("phone_check:pause", detail={"job_id": job_id})
    return {"ok": True, "status": "paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_phone_check_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    if job.status not in {"paused", "interrupted"}:
        raise HTTPException(409, "Tác vụ hiện không thể tiếp tục")
    job.status = "queued"
    job.runner_id = None
    job.finished_at = None
    job.heartbeat_at = utcnow()
    await db.commit()
    await log_audit("phone_check:resume", detail={"job_id": job_id})
    return {"ok": True, "status": "queued"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_phone_check_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    if job.status in {"completed", "completed_with_errors", "cancelled", "failed"}:
        return {"ok": False, "status": job.status}
    job.status = "cancelling"
    job.heartbeat_at = utcnow()
    await db.commit()
    await log_audit("phone_check:cancel", detail={"job_id": job_id})
    return {"ok": True, "status": "cancelling"}


@router.post("/jobs/{job_id}/rebalance")
async def rebalance_phone_check_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    if job.status not in {"queued", "running", "paused", "interrupted"}:
        raise HTTPException(409, "Tác vụ hiện không thể phân phối lại")
    account_rows = (await db.execute(
        select(PhoneCheckAccount).where(PhoneCheckAccount.job_id == job_id).order_by(PhoneCheckAccount.id)
    )).scalars().all()
    ready_ids = [r.account_id for r in account_rows if r.account_id and manager.get(r.account_id)]
    if not ready_ids:
        raise HTTPException(409, "Không có tài khoản đang kết nối để nhận lại công việc")
    safe_statuses = {"queued", "retry_required", "temporary_error", "rate_limited", "in_flight_unknown"}
    items = (await db.execute(
        select(PhoneCheckItem).where(
            PhoneCheckItem.job_id == job_id,
            PhoneCheckItem.status.in_(safe_statuses),
        ).order_by(PhoneCheckItem.id)
    )).scalars().all()
    moved = 0
    cursor = 0
    ready = set(ready_ids)
    for item in items:
        if item.account_id in ready:
            continue
        item.account_id = ready_ids[cursor % len(ready_ids)]
        cursor += 1
        moved += 1
    counts = Counter(item.account_id for item in (await db.execute(
        select(PhoneCheckItem).where(PhoneCheckItem.job_id == job_id, PhoneCheckItem.account_id.is_not(None))
    )).scalars().all())
    for row in account_rows:
        row.assigned_total = int(counts.get(row.account_id, 0))
        if row.account_id in ready and row.status in {"stopped", "waiting_connection", "paused"}:
            row.status = "queued"
        row.updated_at = utcnow()
    job.heartbeat_at = utcnow()
    await db.commit()
    await log_audit("phone_check:rebalance", detail={"job_id": job_id, "moved": moved, "ready_accounts": len(ready_ids)})
    return {"ok": True, "moved": moved, "ready_accounts": ready_ids}


async def _export_rows(db: AsyncSession, job_id: str, status: str | None = None, q: str | None = None):
    job = await db.get(BulkJob, job_id)
    if not job or job.type != "phone_check":
        raise HTTPException(404, "Không tìm thấy tác vụ check số")
    rows = (await db.execute(
        select(PhoneCheckItem).where(*_item_filters(job_id, status, q)).order_by(PhoneCheckItem.id)
    )).scalars().all()
    return job, rows


@router.get("/jobs/{job_id}/export.json")
async def export_phone_check_json(job_id: str, status: str | None = Query(None), q: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_db)):
    job, rows = await _export_rows(db, job_id, status, q)
    payload = json.dumps({"job": _job_dict(job), "results": [_item_dict(row) for row in rows]}, ensure_ascii=False, default=str)
    return StreamingResponse(io.BytesIO(payload.encode("utf-8")), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="phone-check-{job_id}.json"'})


@router.get("/jobs/{job_id}/export.xlsx")
async def export_phone_check_xlsx(job_id: str, status: str | None = Query(None), q: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_db)):
    _job, rows = await _export_rows(db, job_id, status, q)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("results")
    ws.append(["original_phone", "normalized_phone", "status", "account_id", "telegram_user_id", "username", "first_name", "last_name", "presence", "last_online_at", "attempts", "error_code", "error_detail"])
    for row in rows:
        ws.append([row.original_phone, row.normalized_phone or "", row.status, row.account_id or "", row.telegram_user_id or "", row.username or "", row.first_name or "", row.last_name or "", row.presence or "", str(row.last_online_at or ""), row.attempts, row.error_code or "", row.error_detail or ""])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="phone-check-{job_id}.xlsx"'},
    )


@router.get("/jobs/{job_id}/export.csv")
async def export_phone_check_csv(job_id: str, status: str | None = Query(None), q: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_db)):
    _job, rows = await _export_rows(db, job_id, status, q)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["original_phone", "normalized_phone", "status", "account_id", "telegram_user_id", "username", "first_name", "last_name", "presence", "last_online_at", "attempts", "error_code", "error_detail"])
    for row in rows:
        writer.writerow([row.original_phone, row.normalized_phone or "", row.status, row.account_id or "", row.telegram_user_id or "", row.username or "", row.first_name or "", row.last_name or "", row.presence or "", row.last_online_at or "", row.attempts, row.error_code or "", row.error_detail or ""])
    data = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(io.BytesIO(data), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="phone-check-{job_id}.csv"'})
