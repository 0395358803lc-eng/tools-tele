from __future__ import annotations

from sqlalchemy import select

from .config import settings
from .db import AsyncSessionLocal
from .models import AppSetting

DEFAULTS = {
    "rate_min": lambda: str(settings.RATE_MIN),
    "rate_max": lambda: str(settings.RATE_MAX),
    "concurrency": lambda: str(settings.CONCURRENCY),
    "sessions_dir": lambda: settings.SESSIONS_DIR,
    "auto_reconnect": lambda: "true" if settings.AUTO_RECONNECT else "false",
    "notification_sound": lambda: "true" if settings.NOTIFICATION_SOUND else "false",
}


def defaults() -> dict[str, str]:
    return {k: factory() for k, factory in DEFAULTS.items()}


def _bool(value: str, fallback: bool) -> bool:
    if value.lower() in {"true", "1", "yes", "on"}:
        return True
    if value.lower() in {"false", "0", "no", "off"}:
        return False
    return fallback


def apply_runtime(values: dict[str, str], *, include_sessions_dir: bool = False) -> None:
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


async def read_settings() -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(AppSetting))
        values = defaults()
        values.update({row.key: row.value for row in res.scalars().all()})
        return values


async def load_runtime_settings() -> dict[str, str]:
    values = await read_settings()
    apply_runtime(values, include_sessions_dir=True)
    settings.sessions_path
    return values
