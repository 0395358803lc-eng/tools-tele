from __future__ import annotations

from datetime import datetime
from typing import Any

from .time_utils import utcnow
from .db import AsyncSessionLocal
from .models import AuditLog

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
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(
                action=action[:64],
                account_id=account_id,
                detail=_sanitize(detail or {}),
                created_at=utcnow(),
            ))
            await db.commit()
    except Exception:
        # Auditing must not turn a completed Telegram action into an API failure.
        pass
