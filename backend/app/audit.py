from __future__ import annotations

from datetime import datetime
from contextvars import ContextVar
from typing import Any

from .time_utils import utcnow
from .db import AsyncSessionLocal
from .models import AuditLog

_audit_request_id: ContextVar[str] = ContextVar("audit_request_id", default="")
_audit_ip: ContextVar[str] = ContextVar("audit_ip", default="")


def set_audit_request_context(request_id: str, ip: str):
    return (_audit_request_id.set(request_id or ""), _audit_ip.set(ip or ""))


def reset_audit_request_context(tokens) -> None:
    _audit_request_id.reset(tokens[0]); _audit_ip.reset(tokens[1])


def current_audit_context() -> dict[str, str]:
    return {"request_id": _audit_request_id.get(), "ip": _audit_ip.get()}


_SENSITIVE_PARTS = (
    "password", "secret", "token", "code", "otp", "message", "text", "hash",
)


def _sanitize(value: Any, key: str = "") -> Any:
    if any(part in key.lower() for part in _SENSITIVE_PARTS):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:255]
    if isinstance(value, dict):
        return {str(k)[:80]: _sanitize(v, str(k)) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v, key) for v in list(value)[:100]]
    return str(value)[:255]


async def log_audit(action: str, account_id: int | None = None, detail: dict | None = None) -> None:
    """Best-effort operational audit that never stores common secret/message fields."""
    try:
        enriched = dict(detail or {})
        if _audit_request_id.get():
            enriched.setdefault("request_id", _audit_request_id.get()[:64])
        if _audit_ip.get():
            enriched.setdefault("ip", _audit_ip.get()[:128])
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(
                action=action[:64],
                account_id=account_id,
                detail=_sanitize(enriched),
                created_at=utcnow(),
            ))
            await db.commit()
    except Exception:
        # Auditing must not turn a completed Telegram action into an API failure.
        pass
