from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from .time_utils import utcnow
from .config import settings
from .db import AsyncSessionLocal
from .models import Account, BulkJob

_STARTED_AT = utcnow()


def expected_db_revision() -> str | None:
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


async def current_db_revision() -> str | None:
    async with AsyncSessionLocal() as db:
        try:
            return await db.scalar(text('SELECT version_num FROM alembic_version'))
        except Exception:
            return None


async def readiness() -> dict:
    expected = expected_db_revision()
    current = await current_db_revision()
    db_ok = current is not None
    schema_ok = bool(expected and current == expected)
    telegram_cfg = bool(settings.TG_API_ID and settings.TG_API_HASH)
    secret_store = bool(settings.SECRETS_ENCRYPTION_KEY)
    app_auth = bool(settings.APP_PASSWORD and len(settings.APP_PASSWORD) >= 12)
    db_kind = 'postgresql' if settings.database_url.startswith('postgresql') else 'sqlite'
    production = os.environ.get('NODE_ENV', '').strip().lower() == 'production'
    persistent_ok = (not production) or db_kind == 'postgresql'
    singleton_ok = (not production) or bool(settings.ENFORCE_SINGLE_INSTANCE)
    checks = {
        'database': db_ok,
        'schema': schema_ok,
        'app_auth': app_auth,
        'telegram': telegram_cfg,
        'encrypted_session_store': secret_store,
        'persistent_storage': persistent_ok,
        'single_instance_guard': singleton_ok,
    }
    return {
        'ok': all(checks.values()),
        'database': 'ok' if db_ok else 'error',
        'schema': 'ok' if schema_ok else 'out_of_date',
        'db_revision': current,
        'expected_revision': expected,
        'database_kind': db_kind,
        'production_mode': production,
        'app_auth_configured': app_auth,
        'telegram_configured': telegram_cfg,
        'encrypted_session_store': secret_store,
        'persistent_storage': persistent_ok,
        'single_instance_guard': singleton_ok,
        'failed_checks': [name for name, passed in checks.items() if not passed],
    }


async def operational_status() -> dict:
    now = utcnow()
    stale_cutoff = now - timedelta(minutes=3)
    async with AsyncSessionLocal() as db:
        status_rows = (await db.execute(
            select(Account.status, func.count(Account.id))
            .where(Account.deleted_at.is_(None))
            .group_by(Account.status)
        )).all()
        active_jobs = await db.scalar(select(func.count(BulkJob.id)).where(BulkJob.status.in_(['queued','running','cancelling']))) or 0
        stale_jobs = await db.scalar(select(func.count(BulkJob.id)).where(
            BulkJob.status.in_(['queued','running','cancelling']),
            BulkJob.heartbeat_at.is_not(None),
            BulkJob.heartbeat_at < stale_cutoff,
        )) or 0
        failed_jobs_24h = await db.scalar(select(func.count(BulkJob.id)).where(
            BulkJob.created_at >= now - timedelta(hours=24),
            BulkJob.status.in_(['failed', 'completed_with_errors']),
        )) or 0

    db_kind = 'postgresql' if settings.database_url.startswith('postgresql') else 'sqlite'
    return {
        'pid': os.getpid(),
        'started_at': _STARTED_AT,
        'uptime_seconds': max(0, int((now - _STARTED_AT).total_seconds())),
        'database_kind': db_kind,
        'persistent_database': db_kind == 'postgresql',
        'single_instance_guard': bool(settings.ENFORCE_SINGLE_INSTANCE),
        'db_revision': await current_db_revision(),
        'expected_revision': expected_db_revision(),
        'accounts': dict(status_rows),
        'account_total': sum(int(v) for _, v in status_rows),
        'active_jobs': int(active_jobs),
        'stale_jobs': int(stale_jobs),
        'failed_jobs_24h': int(failed_jobs_24h),
    }
