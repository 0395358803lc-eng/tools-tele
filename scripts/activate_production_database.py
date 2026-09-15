#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
PYTHON = str((ROOT.parents[1] / '.venv' / 'bin' / 'python'))
if not Path(PYTHON).exists():
    PYTHON = sys.executable

TABLES = [
    'accounts', 'app_settings', 'gone_accounts', 'security_messages',
    'telegram_sessions', 'app_sessions', 'login_attempts',
    'account_status_history', 'bulk_jobs', 'bulk_job_items', 'audit_logs',
    'target_checks', 'target_check_results', 'encrypted_secrets',
    'message_dispatch_items', 'account_proxies', 'phone_check_items', 'phone_check_accounts',
]


def env_values() -> dict[str, str]:
    values = {k: str(v or '') for k, v in dotenv_values(BACKEND / '.env').items()}
    values.update({k: v for k, v in os.environ.items() if v is not None})
    return values


def async_url(raw: str) -> str:
    if raw.startswith('postgres://'):
        return 'postgresql+asyncpg://' + raw[len('postgres://'):]
    if raw.startswith('postgresql://'):
        return 'postgresql+asyncpg://' + raw[len('postgresql://'):]
    return raw


def source_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    db = sqlite3.connect(path)
    try:
        integrity = db.execute('PRAGMA integrity_check').fetchone()
        if not integrity or str(integrity[0]).lower() != 'ok':
            raise RuntimeError('SQLite source failed integrity_check')
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in TABLES if table in present}
    finally:
        db.close()


async def postgres_counts(raw_url: str) -> dict[str, int]:
    engine = create_async_engine(async_url(raw_url), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = {}
            for table in TABLES:
                exists = await conn.scalar(text('SELECT to_regclass(:name)'), {'name': f'public.{table}'})
                if exists:
                    result[table] = int(await conn.scalar(text(f'SELECT COUNT(*) FROM "{table}"')) or 0)
            return result
    finally:
        await engine.dispose()


def run(cmd: list[str], *, env: dict[str, str], cwd: Path = ROOT) -> None:
    safe = [part if not part.startswith(('postgres://', 'postgresql://', 'postgresql+asyncpg://')) else '<DATABASE_URL>' for part in cmd]
    print('RUN', ' '.join(safe))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description='Kích hoạt PostgreSQL production mà không in secret')
    ap.add_argument('--copy-sqlite', action='store_true', help='Sao chép backend/app.db vào PostgreSQL target TRỐNG đã migrate')
    ap.add_argument('--source', type=Path, default=BACKEND / 'app.db')
    ap.add_argument('--backup-output', type=Path, default=None)
    ap.add_argument('--strict-after', action='store_true', help='Yêu cầu chạy production preflight đầy đủ sau khi kích hoạt DB')
    args = ap.parse_args()

    values = env_values()
    db_url = (values.get('DATABASE_URL') or '').strip()
    if not db_url.startswith(('postgres://', 'postgresql://', 'postgresql+asyncpg://')):
        raise SystemExit('BỊ CHẶN: DATABASE_URL không phải URL PostgreSQL. Hãy cấp phát PostgreSQL production trước.')

    child_env = os.environ.copy()
    child_env.update(values)
    child_env['DATABASE_URL'] = db_url

    print('[1/5] Đang áp dụng Alembic head cho PostgreSQL')
    run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], env=child_env, cwd=BACKEND)

    print('[2/5] Đang xác minh kết nối PostgreSQL/schema head')
    run([PYTHON, str(ROOT / 'scripts' / 'production_check.py'), '--check-db'], env=child_env)

    before = source_counts(args.source) if args.copy_sqlite else {}
    if args.copy_sqlite:
        print('[3/5] Đang sao chép dữ liệu SQLite sang PostgreSQL target TRỐNG')
        run([PYTHON, str(ROOT / 'scripts' / 'migrate_sqlite_to_postgres.py'), '--source', str(args.source), '--target', db_url, '--dry-run'], env=child_env)
        run([PYTHON, str(ROOT / 'scripts' / 'migrate_sqlite_to_postgres.py'), '--source', str(args.source), '--target', db_url], env=child_env)
        after = asyncio.run(postgres_counts(db_url))
        mismatches = {table: (count, after.get(table, 0)) for table, count in before.items() if count != after.get(table, 0)}
        if mismatches:
            raise SystemExit(f'COUNT_MISMATCH: {mismatches}')
        print('DATA_COUNT_VERIFY_OK tables=', len(before))
    else:
        print('[3/5] Đã bỏ qua sao chép SQLite (chỉ dùng --copy-sqlite với target trống)')

    output = args.backup_output
    if output is None:
        stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        output = ROOT / 'backups' / f'production-postgres-{stamp}.tar.gz'
    print('[4/5] Đang tạo backup database production đầu tiên')
    run([PYTHON, str(ROOT / 'scripts' / 'backup_runtime.py'), '--project-root', str(ROOT), '--output', str(output)], env=child_env)

    print('[5/5] Kiểm tra trước khi chạy production')
    check = [PYTHON, str(ROOT / 'scripts' / 'production_check.py'), '--check-db']
    if args.strict_after:
        check.insert(-1, '--strict')
    run(check, env=child_env)
    print('PRODUCTION_DATABASE_ACTIVATION_OK')


if __name__ == '__main__':
    main()
