from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT.parents[1]
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


class ManagerStatusTests(unittest.TestCase):
    def test_status_refresh_is_bounded_concurrent(self):
        with tempfile.TemporaryDirectory(prefix='mtm_status_concurrency_') as td:
            db_path = Path(td) / 'status.db'
            env = os.environ.copy()
            env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
            env['DATABASE_URL'] = ''
            subprocess.run(
                [PYTHON, '-m', 'alembic', 'upgrade', 'head'],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            code = textwrap.dedent("""
                import asyncio
                from sqlalchemy import select
                from app.config import settings
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tg_manager import manager

                class FakeClient:
                    current = 0
                    max_seen = 0

                    def is_connected(self):
                        return True

                    async def is_user_authorized(self):
                        FakeClient.current += 1
                        FakeClient.max_seen = max(FakeClient.max_seen, FakeClient.current)
                        try:
                            await asyncio.sleep(0.05)
                            return True
                        finally:
                            FakeClient.current -= 1

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        rows = [
                            Account(phone=f'status-{i}', session_file=f's{i}', status='connecting')
                            for i in range(20)
                        ]
                        db.add_all(rows)
                        await db.commit()
                        for row in rows:
                            await db.refresh(row)
                    manager._clients = {row.id: FakeClient() for row in rows}
                    settings.STATUS_CONCURRENCY = 5
                    await manager.refresh_status_all()
                    assert 2 <= FakeClient.max_seen <= 5, FakeClient.max_seen
                    async with AsyncSessionLocal() as db:
                        persisted = (await db.execute(select(Account))).scalars().all()
                        assert len(persisted) == 20
                        assert all(row.status == 'connected' for row in persisted)
                        assert all(row.last_ping_at is not None for row in persisted)
                    manager._clients.clear()

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
