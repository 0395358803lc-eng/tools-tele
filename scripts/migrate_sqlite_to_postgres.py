#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.models import Base  # noqa: E402

TABLES = [
    'accounts', 'app_settings', 'gone_accounts', 'security_messages',
    'telegram_sessions', 'app_sessions', 'login_attempts',
    'account_status_history', 'bulk_jobs', 'bulk_job_items', 'audit_logs',
    'target_checks', 'target_check_results', 'encrypted_secrets',
    'message_dispatch_items', 'account_proxies', 'phone_check_items', 'phone_check_accounts',
]
SERIAL_TABLES = [
    'accounts', 'gone_accounts', 'security_messages', 'telegram_sessions',
    'app_sessions', 'login_attempts', 'account_status_history',
    'bulk_job_items', 'audit_logs', 'target_check_results', 'message_dispatch_items',
    'phone_check_items', 'phone_check_accounts',
]

BOOLEAN_COLUMNS = {
    'accounts': {'has_2fa'},
    'security_messages': {'is_read'},
    'telegram_sessions': {'is_primary'},
    'login_attempts': {'success'},
    'account_proxies': {'enabled', 'rdns'},
}
DATETIME_COLUMNS = {
    'accounts': {'last_success_at','last_ping_at','flood_wait_until','deleted_at','created_at','updated_at'},
    'app_settings': {'updated_at'},
    'gone_accounts': {'gone_at'},
    'security_messages': {'received_at'},
    'telegram_sessions': {'created_at','last_connected_at'},
    'app_sessions': {'created_at','expires_at','revoked_at','last_seen_at'},
    'login_attempts': {'attempted_at'},
    'account_status_history': {'created_at'},
    'bulk_jobs': {'created_at','started_at','finished_at','heartbeat_at'},
    'bulk_job_items': {'started_at','finished_at'},
    'audit_logs': {'created_at'},
    'target_checks': {'created_at'},
    'encrypted_secrets': {'updated_at'},
    'message_dispatch_items': {'started_at','finished_at'},
    'account_proxies': {'last_checked_at','created_at','updated_at'},
    'phone_check_items': {'next_retry_at','last_online_at','started_at','checked_at','finished_at','created_at','updated_at'},
    'phone_check_accounts': {'heartbeat_at','created_at','updated_at'},
}
JSON_COLUMNS = {
    'bulk_jobs': {'parameters'},
    'audit_logs': {'detail'},
    'target_checks': {'peer'},
}


def pg_url(raw: str) -> str:
    if raw.startswith('postgres://'):
        return 'postgresql+asyncpg://' + raw[len('postgres://'):]
    if raw.startswith('postgresql://'):
        return 'postgresql+asyncpg://' + raw[len('postgresql://'):]
    return raw


def _datetime(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip().replace('Z', '+00:00')
    parsed = datetime.fromisoformat(raw)
    # Models currently use timezone-naive UTC DateTime columns.
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def normalize_row(table: str, row: dict) -> dict:
    out = dict(row)
    for col in BOOLEAN_COLUMNS.get(table, set()):
        if col in out and out[col] is not None:
            out[col] = bool(out[col])
    for col in DATETIME_COLUMNS.get(table, set()):
        if col in out:
            out[col] = _datetime(out[col])
    for col in JSON_COLUMNS.get(table, set()):
        if col in out and isinstance(out[col], str):
            raw = out[col].strip()
            out[col] = json.loads(raw) if raw else None
    return out


def read_sqlite(path: Path) -> dict[str, list[dict]]:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    try:
        integrity = db.execute('PRAGMA integrity_check').fetchone()
        if not integrity or str(integrity[0]).lower() != 'ok':
            raise RuntimeError('SQLite source failed integrity_check')
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: [normalize_row(table, dict(r)) for r in db.execute(f'SELECT * FROM "{table}"')]
            if table in present else []
            for table in TABLES
        }
    finally:
        db.close()


async def assert_empty_target(conn) -> None:
    missing = []
    nonempty = []
    for table in TABLES:
        exists = await conn.scalar(text('SELECT to_regclass(:name)'), {'name': f'public.{table}'})
        if not exists:
            missing.append(table)
            continue
        count = await conn.scalar(text(f'SELECT COUNT(*) FROM "{table}"'))
        if int(count or 0) > 0:
            nonempty.append((table, int(count)))
    if missing:
        raise RuntimeError('Target schema is incomplete. Run Alembic on PostgreSQL first. Missing: ' + ', '.join(missing))
    if nonempty:
        detail = ', '.join(f'{name}={count}' for name, count in nonempty)
        raise RuntimeError('Target PostgreSQL is not empty; refusing to duplicate/overwrite data: ' + detail)


async def migrate(source: Path, target: str, dry_run: bool) -> None:
    data = read_sqlite(source)
    print('source_rows', {k: len(v) for k, v in data.items()})
    if dry_run:
        print('dry_run_ok')
        return

    engine = create_async_engine(pg_url(target), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await assert_empty_target(conn)
            for table in TABLES:
                rows = data[table]
                if not rows:
                    continue
                table_obj = Base.metadata.tables.get(table)
                if table_obj is None:
                    raise RuntimeError(f"No SQLAlchemy model metadata for table: {table}")
                await conn.execute(table_obj.insert(), rows)
                print('copied', table, len(rows))

            for table in SERIAL_TABLES:
                await conn.execute(text(
                    f"""SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE((SELECT MAX(id) FROM "{table}"), 1),
                        EXISTS(SELECT 1 FROM "{table}")
                    )"""
                ))
    finally:
        await engine.dispose()
    print('migration_complete')


def main() -> None:
    parser = argparse.ArgumentParser(description='Sao chép dữ liệu Multi TG Manager từ SQLite sang PostgreSQL TRỐNG đã được migrate')
    parser.add_argument('--source', default='backend/app.db', type=Path)
    parser.add_argument('--target', required=True, help='DATABASE_URL của PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Chỉ xác minh/đọc/chuẩn hóa SQLite; không kết nối PostgreSQL')
    args = parser.parse_args()
    if not args.source.exists():
        raise SystemExit(f'Không tìm thấy nguồn SQLite: {args.source}')
    if not args.target.startswith(('postgres://','postgresql://','postgresql+asyncpg://')):
        raise SystemExit('--target phải là URL PostgreSQL')
    asyncio.run(migrate(args.source, args.target, args.dry_run))


if __name__ == '__main__':
    main()
