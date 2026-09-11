from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return naive UTC for SQL columns while avoiding deprecated datetime.utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)
