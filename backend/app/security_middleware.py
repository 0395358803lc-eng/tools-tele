from __future__ import annotations

from urllib.parse import urlsplit
import asyncio
import logging
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_COOKIE = "mtm_session"
_log = logging.getLogger("http")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _norm_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except Exception:
        return ""


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
        started = time.perf_counter()

        def finalize(response):
            duration_ms = (time.perf_counter() - started) * 1000
            response.headers["X-Request-ID"] = request_id
            _log.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id, request.method, request.url.path, response.status_code, duration_ms,
            )
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "same-origin")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
            return response

        if request.method.upper() in _UNSAFE and request.cookies.get(_COOKIE):
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            if fetch_site == "cross-site":
                return finalize(JSONResponse({"detail": "Cross-site request blocked"}, status_code=403))

            origin = request.headers.get("origin")
            if origin and _norm_origin(origin) not in _allowed_origins(request):
                return finalize(JSONResponse({"detail": "Origin not allowed"}, status_code=403))

        timeout_s = max(0.1, float(getattr(settings, "API_REQUEST_TIMEOUT_SECONDS", 60.0)))
        try:
            response = await asyncio.wait_for(call_next(request), timeout=timeout_s)
        except asyncio.TimeoutError:
            response = JSONResponse(
                {"detail": f"Request timed out after {timeout_s:.0f}s"},
                status_code=504,
            )
        return finalize(response)
