from __future__ import annotations

from sqlalchemy import select

from .config import settings
from .db import AsyncSessionLocal
from .models import AppSetting
from .tenant import current_tenant_id, tenant_scope

DEFAULTS = {
    "rate_min": lambda: str(settings.RATE_MIN),
    "rate_max": lambda: str(settings.RATE_MAX),
    "concurrency": lambda: str(settings.CONCURRENCY),
    "sessions_dir": lambda: settings.SESSIONS_DIR,
    "auto_reconnect": lambda: "true" if settings.AUTO_RECONNECT else "false",
    "notification_sound": lambda: "true" if settings.NOTIFICATION_SOUND else "false",
}


def defaults() -> dict[str, str]:
    return {key: factory() for key, factory in DEFAULTS.items()}


def _bool(value: str, fallback: bool) -> bool:
    if value.lower() in {"true", "1", "yes", "on"}:
        return True
    if value.lower() in {"false", "0", "no", "off"}:
        return False
    return fallback

def apply_runtime(values: dict[str, str], *, include_sessions_dir: bool = False) -> None:
    """Apply server defaults only. User settings are persisted per tenant and are not global."""
    try:
        settings.RATE_MIN = max(0.0, float(values.get("rate_min", settings.RATE_MIN)))
        settings.RATE_MAX = max(settings.RATE_MIN, float(values.get("rate_max", settings.RATE_MAX)))
        settings.CONCURRENCY = max(1, min(50, int(float(values.get("concurrency", settings.CONCURRENCY)))))
    except (TypeError, ValueError):
        pass
    settings.AUTO_RECONNECT = _bool(
        values.get("auto_reconnect", str(settings.AUTO_RECONNECT)), settings.AUTO_RECONNECT
    )
    settings.NOTIFICATION_SOUND = _bool(
        values.get("notification_sound", str(settings.NOTIFICATION_SOUND)), settings.NOTIFICATION_SOUND
    )
    if include_sessions_dir:
        value = (values.get("sessions_dir") or "").strip()
        if value:
            settings.SESSIONS_DIR = value


async def read_settings(user_id: str | None = None) -> dict[str, str]:
    uid = str(user_id or current_tenant_id() or "").strip()
    values = defaults()
    if not uid:
        return values
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(AppSetting))).scalars().all()
            prefix = f"user:{uid}:"
            for row in rows:
                key = row.key[len(prefix):] if row.key.startswith(prefix) else row.key
                values[key] = row.value
    return values


async def bulk_limits(user_id: str | None = None) -> tuple[float, float, int]:
    values = await read_settings(user_id)
    try:
        lo = max(0.0, float(values.get("rate_min", settings.RATE_MIN)))
    except (TypeError, ValueError):
        lo = max(0.0, float(settings.RATE_MIN))
    try:
        hi = max(lo, float(values.get("rate_max", settings.RATE_MAX)))
    except (TypeError, ValueError):
        hi = max(lo, float(settings.RATE_MAX))
    try:
        conc = max(1, min(50, int(float(values.get("concurrency", settings.CONCURRENCY)))))
    except (TypeError, ValueError):
        conc = max(1, min(50, int(settings.CONCURRENCY)))
    return lo, hi, conc


async def auto_reconnect_enabled(user_id: str | None = None) -> bool:
    values = await read_settings(user_id)
    return _bool(values.get("auto_reconnect", str(settings.AUTO_RECONNECT)), settings.AUTO_RECONNECT)


async def load_runtime_settings() -> dict[str, str]:
    """Startup applies server defaults only; tenant preferences are loaded per request."""
    values = defaults()
    apply_runtime(values, include_sessions_dir=True)
    settings.sessions_path
    return values
