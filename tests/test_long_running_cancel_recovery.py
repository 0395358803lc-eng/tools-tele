import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = str(Path(sys.executable))


class LongRunningCancelRecoveryTests(unittest.TestCase):
    def test_cancel_recovery_closes_items_and_secret(self):
        with tempfile.TemporaryDirectory(prefix="mtm_cancel_recovery_") as td:
            db_path = Path(td) / "jobs.db"
            env = os.environ.copy()
            env["DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
            env["DATABASE_URL"] = ""
            env["SESSIONS_DIR"] = str(Path(td) / "sessions")
            subprocess.run(
                [PYTHON, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            code = textwrap.dedent(r'''
                import asyncio
                from sqlalchemy import select
                from app import secrets_store
                from app.db import AsyncSessionLocal
                from app.message_dispatch_runner import (
                    _secret_name, create_message_job, message_dispatch_runner,
                )
                from app.models import Account, BulkJob, MessageDispatchItem
                from app.tenant import set_tenant_id

                async def main():
                    uid = '00000000-0000-4000-8000-000000000105'
                    set_tenant_id(uid)
                    async with AsyncSessionLocal() as db:
                        acc = Account(
                            phone='+10006', session_file='a', status='connected'
                        )
                        db.add(acc)
                        await db.commit()
                        await db.refresh(acc)
                    job_id = await create_message_job(
                        [(acc.id, acc.phone, 'A')],
                        [('@a', 'user:a'), ('@b', 'user:b')],
                        'secret-cancel',
                    )
                    async with AsyncSessionLocal() as db:
                        job = await db.get(BulkJob, job_id)
                        job.status = 'cancelling'
                        await db.commit()

                    await message_dispatch_runner.recover_stale()

                    async with AsyncSessionLocal() as db:
                        job = await db.get(BulkJob, job_id)
                        rows = (await db.execute(
                            select(MessageDispatchItem).where(
                                MessageDispatchItem.job_id == job_id
                            )
                        )).scalars().all()
                        assert job.status == 'cancelled'
                        assert job.pending == 0
                        assert rows and all(row.status == 'cancelled' for row in rows)

                    assert await secrets_store.get_named_secret(
                        _secret_name(job_id), uid
                    ) is None

                asyncio.run(main())
            ''')
            subprocess.run([PYTHON, "-c", code], cwd=BACKEND, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
