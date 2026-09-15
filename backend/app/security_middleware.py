from __future__ import annotations

from urllib.parse import urlsplit
import asyncio
import logging
from collections import deque
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .audit import reset_audit_request_context, set_audit_request_context
from .runtime_metrics import observe_request

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_COOKIE = "mtm_session"
_log = logging.getLogger("http")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = {}


def _norm_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except Exception:
        return ""


def _client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:128]
    return (request.client.host if request.client else "unknown")[:128]


def _rate_limit(request: Request) -> tuple[bool, int]:
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/health"):
        return True, 0
    if path.startswith("/api/admin"):
        bucket, limit = "admin", int(settings.ADMIN_RATE_LIMIT_PER_MIN)
    elif path.startswith("/api/auth-app"):
        bucket, limit = "auth", int(settings.AUTH_RATE_LIMIT_PER_MIN)
    else:
        bucket, limit = "api", int(settings.API_RATE_LIMIT_PER_MIN)
    if limit <= 0:
        return True, 0
    now = time.monotonic()
    key = (bucket, _client_ip(request))
    cutoff = now - 60.0
    if key not in _RATE_BUCKETS and len(_RATE_BUCKETS) >= 10000:
        stale = [k for k, values in _RATE_BUCKETS.items() if not values or values[-1] <= cutoff]
        for stale_key in stale[:2000]:
            _RATE_BUCKETS.pop(stale_key, None)
        if len(_RATE_BUCKETS) >= 10000:
            oldest = min(_RATE_BUCKETS, key=lambda k: _RATE_BUCKETS[k][-1] if _RATE_BUCKETS[k] else -1)
            _RATE_BUCKETS.pop(oldest, None)
    q = _RATE_BUCKETS.setdefault(key, deque())
    while q and q[0] <= cutoff:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(60 - (now - q[0])))
        return False, retry
    q.append(now)
    return True, 0


def _request_origin(request: Request) -> str:
    scheme = request.url.scheme
    host = request.headers.get("host", "")
    if settings.TRUST_PROXY_HEADERS:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        if proto:
            scheme = proto
        if forwarded_host:
            host = forwarded_host
    return _norm_origin(f"{scheme}://{host}")


def _allowed_origins(request: Request) -> set[str]:
    allowed = {_request_origin(request)}
    for raw in (settings.ALLOWED_ORIGIN, settings.CSRF_TRUSTED_ORIGINS):
        for item in (raw or "").split(","):
            origin = _norm_origin(item)
            if origin:
                allowed.add(origin)
    allowed.discard("")
    return allowed


class BrowserSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied = (request.headers.get("x-request-id") or "").strip()
        request_id = supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        def finalize(response):
            duration_ms = (time.perf_counter() - started) * 1000
            observe_request(response.status_code, duration_ms)
            response.headers["X-Request-ID"] = request_id
            _log.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id, request.method, request.url.path, response.status_code, duration_ms,
            )
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "same-origin")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            if request.url.path.startswith('/api/'):
                response.headers.setdefault("Cache-Control", "no-store")
            if _request_origin(request).startswith('https://'):
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            connect_sources = ["'self'"]
            supabase_origin = _norm_origin(settings.SUPABASE_URL)
            if supabase_origin:
                connect_sources.append(supabase_origin)
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                f"script-src 'self'; connect-src {' '.join(connect_sources)}; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
            return response

        allowed, retry_after = _rate_limit(request)
        if not allowed:
            return finalize(JSONResponse({"detail": "Quá nhiều yêu cầu; vui lòng thử lại sau"}, status_code=429, headers={"Retry-After": str(retry_after)}))

        if request.method.upper() in _UNSAFE and request.cookies.get(_COOKIE):
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            if fetch_site == "cross-site":
                return finalize(JSONResponse({"detail": "Cross-site request blocked"}, status_code=403))

            origin = request.headers.get("origin")
            if origin and _norm_origin(origin) not in _allowed_origins(request):
                return finalize(JSONResponse({"detail": "Origin not allowed"}, status_code=403))

        timeout_s = max(0.1, float(getattr(settings, "API_REQUEST_TIMEOUT_SECONDS", 60.0)))
        audit_tokens = set_audit_request_context(request_id, _client_ip(request))
        try:
            try:
                response = await asyncio.wait_for(call_next(request), timeout=timeout_s)
            except asyncio.TimeoutError:
                response = JSONResponse(
                    {"detail": f"Request timed out after {timeout_s:.0f}s"},
                    status_code=504,
                )
            return finalize(response)
        finally:
            reset_audit_request_context(audit_tokens)
