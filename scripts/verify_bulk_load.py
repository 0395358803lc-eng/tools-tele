#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


async def worker(account_count: int, concurrency: int) -> dict:
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import func, select
    from app.config import settings
    from app.db import AsyncSessionLocal
    from app.models import Account, BulkJob, BulkJobItem
    from app.tg_manager import manager
    from app.utils import bulk_stream

    async with AsyncSessionLocal() as db:
        rows = [
            Account(
                phone=f'load-{i:04d}',
                session_file=f'load_{i:04d}',
                status='connected',
            )
            for i in range(account_count)
        ]
        db.add_all(rows)
        await db.commit()
        for row in rows:
            await db.refresh(row)
        accounts = [(r.id, r.phone, r.phone) for r in rows]

    for aid, _, _ in accounts:
        manager._clients[aid] = object()

    settings.RATE_MIN = 0
    settings.RATE_MAX = 0
    settings.CONCURRENCY = concurrency
    settings.TG_RPC_TIMEOUT_SECONDS = 5

    async def action(_client, _account_id):
        await asyncio.sleep(0.005)
        return 'ok', ''

    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    events = []
    async for line in bulk_stream(accounts, action, job_type='load_test'):
        events.append(json.loads(line))
    wall_s = time.perf_counter() - wall_start
    cpu_s = time.process_time() - cpu_start

    done = [e for e in events if e.get('type') == 'done'][-1]
    job_id = done['job_id']
    async with AsyncSessionLocal() as db:
        job = await db.get(BulkJob, job_id)
        item_count = await db.scalar(
            select(func.count(BulkJobItem.id)).where(BulkJobItem.job_id == job_id)
        )
        ok_count = await db.scalar(
            select(func.count(BulkJobItem.id)).where(
                BulkJobItem.job_id == job_id,
                BulkJobItem.status == 'ok',
            )
        )

    for aid, _, _ in accounts:
        manager._clients.pop(aid, None)

    assert job is not None
    assert job.status == 'completed'
    assert job.success == account_count
    assert done['success'] == account_count
    assert int(item_count or 0) == account_count
    assert int(ok_count or 0) == account_count

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        'accounts': account_count,
        'concurrency': concurrency,
        'wall_seconds': round(wall_s, 3),
        'cpu_seconds': round(cpu_s, 3),
        'max_rss_kib': int(rss),
        'job_id': job_id,
        'success': done['success'],
        'failed': done['failed'],
        'skipped': done['skipped'],
        'pending': done['pending'],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description='Xác minh offline scheduler hàng loạt/tải SQL')
    ap.add_argument('--accounts', type=int, default=100)
    ap.add_argument('--concurrency', type=int, default=20)
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()
    accounts = max(1, min(1000, args.accounts))
    concurrency = max(1, min(50, args.concurrency))

    if args.worker:
        print(json.dumps(asyncio.run(worker(accounts, concurrency)), sort_keys=True))
        return

    with tempfile.TemporaryDirectory(prefix='mtm_bulk_load_') as td:
        db_path = Path(td) / 'load.db'
        env = os.environ.copy()
        env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
        env['DATABASE_URL'] = ''
        subprocess.run(
            [PYTHON, '-m', 'alembic', 'upgrade', 'head'],
            cwd=BACKEND, env=env, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        result = subprocess.run(
            [PYTHON, str(Path(__file__).resolve()), '--worker', '--accounts', str(accounts), '--concurrency', str(concurrency)],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        )
        line = [ln for ln in result.stdout.splitlines() if ln.strip()][-1]
        metrics = json.loads(line)
        metrics['db_bytes'] = db_path.stat().st_size
        print(json.dumps(metrics, indent=2, sort_keys=True))
        if metrics['failed'] or metrics['pending'] or metrics['skipped']:
            raise SystemExit('xác minh tải hàng loạt có kết quả không thành công')
        print('BULK_LOAD_VERIFY_OK')


if __name__ == '__main__':
    main()
