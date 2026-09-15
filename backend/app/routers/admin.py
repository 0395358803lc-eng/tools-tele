from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import job_store
from ..admin_service import admin_audit, admin_health, admin_jobs, dashboard_counts, purge_tenant_data, tenant_usage
from ..audit import log_audit
from ..auth import require_admin
from ..db import AsyncSessionLocal
from ..models import BulkJob
from ..quota import DEFAULT_QUOTAS, clear_quota_cache, normalize_quotas
from ..supabase_identity import (
    IdentityUser, create_identity_user, delete_identity_user,
    force_logout_identity_user, get_identity_user, list_users,
    update_identity_user,
)
from ..tenant import system_scope, tenant_scope

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "user"] = "user"


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    disabled: bool | None = None
    quotas: dict[str, int] | None = None


class AdminUserPurge(BaseModel):
    confirm_username: str = Field(min_length=1, max_length=128)


def _public(user: IdentityUser) -> dict:
    data = user.__dict__.copy()
    data["quotas"] = normalize_quotas(data.get("quotas"))
    data.pop("session_not_before", None)
    return data


def _request_detail(request: Request, target_user_id: str | None = None) -> dict:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "")
    detail = {
        "ip": ip[:128],
        "request_id": str(getattr(request.state, "request_id", ""))[:64],
    }
    if target_user_id:
        detail["target_user_id"] = target_user_id
    return detail


async def _identity_summary() -> tuple[list[IdentityUser], dict]:
    users = await asyncio.to_thread(list_users)
    summary = {
        "total_users": len(users),
        "active_users": sum(1 for u in users if not u.disabled and u.role in {"admin", "user"}),
        "disabled_users": sum(1 for u in users if u.disabled),
        "unprovisioned_users": sum(1 for u in users if u.role not in {"admin", "user"}),
        "admins": sum(1 for u in users if u.role == "admin"),
    }
    return users, summary


@router.get("/summary")
async def admin_summary(_: IdentityUser = Depends(require_admin)):
    _users, summary = await _identity_summary()
    summary.update(await dashboard_counts())
    return summary


@router.get("/dashboard")
async def admin_dashboard(_: IdentityUser = Depends(require_admin)):
    users, summary = await _identity_summary()
    summary.update(await dashboard_counts())
    return {"summary": summary, "health": await admin_health(),
            "users": [_public(u) for u in users]}


@router.get("/users")
async def admin_users(_: IdentityUser = Depends(require_admin)):
    try:
        users = await asyncio.to_thread(list_users)
        return [_public(u) for u in users]
    except Exception as exc:
        raise HTTPException(502, "Không thể tải danh sách user từ Supabase") from exc


@router.get("/users/{uid}/overview")
async def admin_user_overview(uid: str, _: IdentityUser = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(get_identity_user, uid)
    except Exception as exc:
        raise HTTPException(404, "Không tìm thấy user") from exc
    return {"user": _public(user), "usage": await tenant_usage(uid)}


@router.post("/users")
async def admin_create_user(body: AdminUserCreate, request: Request,
                            current: IdentityUser = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(create_identity_user, body.username, body.password, body.role)
        clear_quota_cache(user.id)
        detail = _request_detail(request, user.id)
        detail.update({"role": body.role})
        await log_audit("admin:user_create", detail=detail)
        return _public(user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Không thể tạo user trên Supabase") from exc


@router.patch("/users/{uid}")
async def admin_update_user(uid: str, body: AdminUserUpdate, request: Request,
                            current: IdentityUser = Depends(require_admin)):
    if uid == current.id and (body.disabled is True or body.role == "user"):
        raise HTTPException(400, "ADMIN đang đăng nhập không thể tự khóa hoặc tự hạ quyền")
    try:
        user = await asyncio.to_thread(update_identity_user, uid, role=body.role,
            password=body.password, disabled=body.disabled, quotas=body.quotas)
        clear_quota_cache(uid)
        detail = _request_detail(request, uid)
        detail.update({"role_changed": body.role is not None,
                       "password_reset": body.password is not None,
                       "disabled": body.disabled, "quotas_changed": body.quotas is not None})
        await log_audit("admin:user_update", detail=detail)
        return _public(user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Không thể cập nhật user trên Supabase") from exc


@router.post("/users/{uid}/force-logout")
async def admin_force_logout(uid: str, request: Request,
                             current: IdentityUser = Depends(require_admin)):
    if uid == current.id:
        raise HTTPException(400, "Không thể force logout chính ADMIN đang thao tác")
    try:
        user = await asyncio.to_thread(force_logout_identity_user, uid)
        clear_quota_cache(uid)
        await log_audit("admin:force_logout", detail=_request_detail(request, uid))
        return {"ok": True, "user": _public(user)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Không thể thu hồi phiên user") from exc


@router.delete("/users/{uid}")
async def admin_delete_user(uid: str, request: Request,
                            current: IdentityUser = Depends(require_admin)):
    if uid == current.id:
        raise HTTPException(400, "ADMIN đang đăng nhập không thể tự xóa")
    try:
        await asyncio.to_thread(delete_identity_user, uid)
        clear_quota_cache(uid)
        await log_audit("admin:user_delete", detail=_request_detail(request, uid))
        return {"ok": True, "business_data_retained": True}
    except Exception as exc:
        raise HTTPException(502, "Không thể xóa user trên Supabase") from exc


@router.post("/users/{uid}/purge")
async def admin_purge_user(uid: str, body: AdminUserPurge, request: Request,
                           current: IdentityUser = Depends(require_admin)):
    if uid == current.id:
        raise HTTPException(400, "ADMIN đang đăng nhập không thể tự xóa vĩnh viễn")
    try:
        target = await asyncio.to_thread(get_identity_user, uid)
        if body.confirm_username.strip() != target.username:
            raise HTTPException(400, "Tên xác nhận không khớp")
        await asyncio.to_thread(update_identity_user, uid, disabled=True, force_logout=True)
        counts = await purge_tenant_data(uid)
        await asyncio.to_thread(delete_identity_user, uid)
        clear_quota_cache(uid)
        detail = _request_detail(request, uid)
        detail.update({"purged_rows": sum(counts.values()), "tables": counts})
        await log_audit("admin:user_purge", detail=detail)
        return {"ok": True, "purged": counts}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Không thể xóa vĩnh viễn user") from exc


@router.get("/audit")
async def admin_audit_list(limit: int = Query(100, ge=1, le=500),
                           offset: int = Query(0, ge=0), user_id: str | None = None,
                           action: str | None = None, account_id: int | None = None,
                           _: IdentityUser = Depends(require_admin)):
    return await admin_audit(limit=limit, offset=offset, user_id=user_id,
                             action=action, account_id=account_id)


@router.get("/jobs")
async def admin_job_list(limit: int = Query(100, ge=1, le=500),
                         user_id: str | None = None, status: str | None = None,
                         job_type: str | None = None,
                         _: IdentityUser = Depends(require_admin)):
    return await admin_jobs(limit=limit, user_id=user_id, status=status, job_type=job_type)


@router.post("/jobs/{job_id}/cancel")
async def admin_cancel_job(job_id: str, request: Request,
                           _: IdentityUser = Depends(require_admin)):
    with system_scope():
        accepted = await job_store.request_cancel(job_id)
    if accepted:
        detail = _request_detail(request)
        detail["job_id"] = job_id
        await log_audit("admin:job_cancel", detail=detail)
    return {"ok": accepted, "job_id": job_id}


@router.post("/jobs/{job_id}/retry")
async def admin_retry_job(job_id: str, request: Request,
                          _: IdentityUser = Depends(require_admin)):
    with system_scope():
        async with AsyncSessionLocal() as db:
            job = await db.get(BulkJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    owner_id = str(job.user_id)
    from .jobs import retry_job as tenant_retry_job
    with tenant_scope(owner_id):
        async with AsyncSessionLocal() as db:
            response = await tenant_retry_job(job_id, db)
        body_iterator = response.body_iterator
    detail = _request_detail(request, owner_id); detail["job_id"] = job_id
    await log_audit("admin:job_retry", detail=detail)

    async def stream():
        with tenant_scope(owner_id):
            async for chunk in body_iterator:
                yield chunk
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.get("/health")
async def admin_system_health(_: IdentityUser = Depends(require_admin)):
    return await admin_health()


@router.get("/quota-defaults")
async def admin_quota_defaults(_: IdentityUser = Depends(require_admin)):
    return DEFAULT_QUOTAS
