#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
from dotenv import dotenv_values
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
for _key, _value in dotenv_values(BACKEND / '.env').items():
    if _value is not None:
        os.environ.setdefault(str(_key), str(_value))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, func, select
from app.config import settings
from app.db import AsyncSessionLocal
from app.models import (
    AccountStatusHistory, AppSession, AuditLog, BulkJob, LoginAttempt,
    SecurityMessage, TargetCheck,
)
from app.tenant import system_scope
from app.time_utils import utcnow

TERMINAL_JOBS = ('completed', 'completed_with_errors', 'failed', 'cancelled', 'interrupted')


def _days(value: int, minimum: int = 1) -> int:
    return max(minimum, int(value))


async def _count(db, model, *conditions) -> int:
    q = select(func.count()).select_from(model)
    if conditions:
        q = q.where(*conditions)
    return int(await db.scalar(q) or 0)


async def cleanup(apply: bool) -> dict[str, int]:
    now = utcnow()
    cutoffs = {
        'audit_logs': now - timedelta(days=_days(settings.RETENTION_AUDIT_DAYS)),
        'account_status_history': now - timedelta(days=_days(settings.RETENTION_STATUS_DAYS)),
        'bulk_jobs': now - timedelta(days=_days(settings.RETENTION_JOBS_DAYS)),
        'security_messages': now - timedelta(days=_days(settings.RETENTION_SECURITY_DAYS)),
        'target_checks': now - timedelta(days=_days(settings.RETENTION_TARGET_CHECK_DAYS)),
        'login_attempts': now - timedelta(days=_days(settings.RETENTION_LOGIN_DAYS)),
        'app_sessions': now - timedelta(days=7),
    }
    counts: dict[str, int] = {}
    with system_scope():
        async with AsyncSessionLocal() as db:
            specs = [
                ('audit_logs', AuditLog, (AuditLog.created_at < cutoffs['audit_logs'],)),
                ('account_status_history', AccountStatusHistory, (AccountStatusHistory.created_at < cutoffs['account_status_history'],)),
                ('security_messages', SecurityMessage, (SecurityMessage.received_at < cutoffs['security_messages'],)),
                ('target_checks', TargetCheck, (TargetCheck.created_at < cutoffs['target_checks'],)),
                ('login_attempts', LoginAttempt, (LoginAttempt.attempted_at < cutoffs['login_attempts'],)),
                ('app_sessions', AppSession, (AppSession.expires_at < cutoffs['app_sessions'],)),
                ('bulk_jobs', BulkJob, (
                    BulkJob.created_at < cutoffs['bulk_jobs'],
                    BulkJob.status.in_(TERMINAL_JOBS),
                )),
            ]
            for name, model, conditions in specs:
                counts[name] = await _count(db, model, *conditions)
                if apply and counts[name]:
                    await db.execute(delete(model).where(*conditions))
            if apply:
                await db.commit()
            else:
                await db.rollback()
    return counts


def write_status(*, ok: bool, apply: bool, counts: dict | None = None, error: str = '') -> None:
    log_dir = ROOT / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'ok': bool(ok), 'apply': bool(apply), 'at': utcnow().isoformat(),
        'counts': counts or {}, 'error': str(error or '')[:500],
    }
    tmp = log_dir / 'maintenance-status.tmp'
    target = log_dir / 'maintenance-status.json'
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apply deletions. Default is dry-run only.')
    args = parser.parse_args()
    try:
        counts = asyncio.run(cleanup(args.apply))
        write_status(ok=True, apply=args.apply, counts=counts)
        try:
            from app.ops_alerts import set_alert
            set_alert('maintenance_failed', False, level='info',
                      message='Maintenance cleanup recovered', source='maintenance')
        except Exception:
            pass
        print(('APPLIED' if args.apply else 'DRY_RUN') + '=' + json.dumps(counts, ensure_ascii=False))
    except Exception as exc:
        write_status(ok=False, apply=args.apply, error=type(exc).__name__)
        try:
            from app.ops_alerts import set_alert
            set_alert('maintenance_failed', True, level='critical',
                      message='Scheduled data-retention cleanup failed', source='maintenance')
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
