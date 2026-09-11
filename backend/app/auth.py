"""Dashboard password authentication backed by revocable SQL sessions."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .time_utils import utcnow
from .config import settings
from .db import AsyncSessionLocal, get_db
from .models import AppSession, LoginAttempt
from .audit import log_audit

COOKIE_NAME = "mtm_session"
_pw_hash: Optional[bytes] = None


def _password_hash() -> bytes:
    global _pw_hash
    if _pw_hash is None:
        if not settings.APP_PASSWORD:
            raise RuntimeError("Chưa cấu hình APP_PASSWORD")
        _pw_hash = bcrypt.hashpw(settings.APP_PASSWORD.encode(), bcrypt.gensalt(rounds=12))
    return _pw_hash


def _verify_password(password: str) -> bool:
    if not password:
        return False
    try:
        return bcrypt.checkpw(password.encode(), _password_hash())
    except Exception:
        return False


def verify_app_password(password: str) -> bool:
    return _verify_password(password)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:128]
    return (request.client.host if request.client else "unknown")[:128]


def _cookie_secure(request: Request) -> bool:
    if settings.COOKIE_SECURE or request.url.scheme == "https":
        return True
    if settings.TRUST_PROXY_HEADERS:
        return request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    return False


async def _find_session(token: str) -> AppSession | None:
    if not token:
        return None
    now = utcnow()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(AppSession).where(
                AppSession.token_hash == _token_hash(token),
                AppSession.revoked_at.is_(None),
                AppSession.expires_at > now,
            )
        )
        row = res.scalar_one_or_none()
        if row:
            row.last_seen_at = now
            await db.commit()
        return row


async def require_auth(request: Request, mtm_session: str = Cookie(None)):
    session = await _find_session(mtm_session or "")
    if not session:
        raise HTTPException(401, "Chưa đăng nhập")
    return True


async def _check_rate(db: AsyncSession, ip: str) -> tuple[bool, int]:
    now = utcnow()
    cutoff = now - timedelta(minutes=max(1, settings.LOGIN_WINDOW_MIN))
    await db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
    res = await db.execute(
        select(LoginAttempt).where(
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        ).order_by(LoginAttempt.attempted_at.asc())
    )
    rows = res.scalars().all()
    if len(rows) >= max(1, settings.LOGIN_MAX_ATTEMPTS):
        remaining = int((rows[0].attempted_at + timedelta(minutes=settings.LOGIN_WINDOW_MIN) - now).total_seconds())
        return False, max(1, remaining)
    return True, 0


async def cleanup_auth_state() -> None:
    """Remove expired dashboard sessions and old login-attempt rows."""
    now = utcnow()
    cutoff = now - timedelta(minutes=max(1, settings.LOGIN_WINDOW_MIN))
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSession).where(AppSession.expires_at <= now))
        await db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
        await db.commit()


router = APIRouter(prefix="/api/auth-app", tags=["auth-app"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = _client_ip(request)
    allowed, retry = await _check_rate(db, ip)
    if not allowed:
        await db.commit()
        raise HTTPException(429, f"Quá nhiều lần thử. Hãy thử lại sau {retry} giây.")

    if not _verify_password(body.password):
        db.add(LoginAttempt(ip=ip, success=False, attempted_at=utcnow()))
        await db.commit()
        await asyncio.sleep(0.4)
        raise HTTPException(401, "Mật khẩu không đúng")

    now = utcnow()
    token = secrets.token_urlsafe(48)
    db.add(AppSession(
        token_hash=_token_hash(token),
        ip=ip,
        user_agent=(request.headers.get("user-agent") or "")[:512],
        created_at=now,
        expires_at=now + timedelta(days=max(1, settings.SESSION_DAYS)),
        last_seen_at=now,
    ))
    await db.execute(delete(LoginAttempt).where(LoginAttempt.ip == ip))
    await db.commit()
    response.set_cookie(
        key=COOKIE_NAME, value=token, max_age=max(1, settings.SESSION_DAYS) * 86400,
        httponly=True, samesite="strict", secure=_cookie_secure(request), path="/",
    )
    await log_audit("auth:login")
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response, mtm_session: str = Cookie(None), db: AsyncSession = Depends(get_db)):
    if mtm_session:
        res = await db.execute(select(AppSession).where(AppSession.token_hash == _token_hash(mtm_session)))
        row = res.scalar_one_or_none()
        if row and row.revoked_at is None:
            row.revoked_at = utcnow()
            await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    await log_audit("auth:logout")
    return {"ok": True}


@router.get("/me")
async def me(mtm_session: str = Cookie(None)):
    return {"authed": bool(await _find_session(mtm_session or ""))}
