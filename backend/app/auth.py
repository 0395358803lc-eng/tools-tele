"""Supabase Auth identity layer for the dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import text

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .tenant import reset_tenant_id, set_tenant_id
from .db import AsyncSessionLocal
from .supabase_identity import (
    IdentityUser,
    create_identity_user,
    has_admin,
    supabase_configured,
    verify_access_token,
    token_claims,
)

router = APIRouter(prefix="/api/auth-app", tags=["auth-app"])
_bootstrap_lock = asyncio.Lock()


class BootstrapIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)


def _bearer_token(request: Request) -> str:
    header = (request.headers.get("authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Chưa đăng nhập")
    token = header[7:].strip()
    if not token:
        raise HTTPException(401, "Chưa đăng nhập")
    return token


async def _session_after_cutoff(user: IdentityUser, token: str) -> bool:
    if not user.session_not_before:
        return True
    claims = token_claims(token)
    session_id = str(claims.get("session_id") or "").strip()
    if not session_id:
        return False
    try:
        cutoff = datetime.fromisoformat(user.session_not_before.replace("Z", "+00:00"))
        async with AsyncSessionLocal() as db:
            ok = await db.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM auth.sessions "
                "WHERE id=CAST(:sid AS uuid) AND user_id=CAST(:uid AS uuid) "
                "AND created_at > :cutoff)"
            ), {"sid": session_id, "uid": user.id, "cutoff": cutoff})
        return bool(ok)
    except Exception:
        return False


async def require_auth(request: Request) -> IdentityUser:
    token = _bearer_token(request)
    try:
        user = await asyncio.to_thread(verify_access_token, token)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn") from exc
    if not await _session_after_cutoff(user, token):
        raise HTTPException(401, "Phiên đăng nhập đã bị ADMIN thu hồi")
    request.state.current_user = user
    tenant_token = set_tenant_id(user.id)
    try:
        yield user
    finally:
        reset_tenant_id(tenant_token)


async def require_admin(user: IdentityUser = Depends(require_auth)) -> IdentityUser:
    if not user.is_admin:
        raise HTTPException(403, "Yêu cầu quyền ADMIN")
    return user


async def cleanup_auth_state() -> None:
    """Compatibility hook: Supabase owns session cleanup and refresh-token state."""
    return None


@router.get("/bootstrap/status")
async def bootstrap_status():
    if not supabase_configured():
        return {"configured": False, "needs_admin": False}
    try:
        exists = await asyncio.to_thread(has_admin)
    except Exception as exc:
        raise HTTPException(503, "Không thể kết nối Supabase Auth") from exc
    return {"configured": True, "needs_admin": not exists}


@router.post("/bootstrap")
async def bootstrap_admin(body: BootstrapIn):
    if not supabase_configured():
        raise HTTPException(503, "Chưa cấu hình Supabase")
    async with _bootstrap_lock:
        try:
            if await asyncio.to_thread(has_admin):
                raise HTTPException(409, "ADMIN đầu tiên đã tồn tại")
            user = await asyncio.to_thread(
                create_identity_user, body.username, body.password, "admin"
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "Không thể tạo ADMIN trên Supabase") from exc
    return {"ok": True, "user": user.__dict__}


@router.get("/me")
async def me(user: IdentityUser = Depends(require_auth)):
    return {"authed": True, "user": user.__dict__}


@router.post("/logout")
async def logout():
    # Refresh-token revocation is performed by supabase-js on the client.
    return {"ok": True}


@router.post("/login", include_in_schema=False)
async def legacy_login_disabled():
    raise HTTPException(410, "Đăng nhập APP_PASSWORD đã được thay bằng Supabase Auth")
