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


class LongRunningJobTests(unittest.TestCase):
    def _run(self, code: str):
        with tempfile.TemporaryDirectory(prefix="mtm_longjob_") as td:
            db_path = Path(td) / "jobs.db"
            env = os.environ.copy()
            env["DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
            env["DATABASE_URL"] = ""
            env["SESSIONS_DIR"] = str(Path(td) / "sessions")
            subprocess.run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
                           env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([PYTHON, "-c", textwrap.dedent(code)], cwd=BACKEND, env=env, check=True)

    def test_observer_disconnect_keeps_job_persisted(self):
        self._run(r'''
            import asyncio, json
            from app.db import AsyncSessionLocal
            from app.message_dispatch_runner import create_message_job, stream_message_job
            from app.models import Account, BulkJob
            from app.tenant import set_tenant_id

            async def main():
                set_tenant_id('00000000-0000-4000-8000-000000000101')
                async with AsyncSessionLocal() as db:
                    acc=Account(phone='+10001', first_name='A', session_file='a', status='connected')
                    db.add(acc); await db.commit(); await db.refresh(acc)
                job_id=await create_message_job([(acc.id,acc.phone,'A')],[('@alpha','user:alpha')],'secret-body')
                stream=stream_message_job(job_id)
                first=json.loads(await anext(stream))
                assert first['job_id']==job_id and first['status']=='queued'
                await stream.aclose()
                async with AsyncSessionLocal() as db:
                    job=await db.get(BulkJob,job_id)
                    assert job.status=='queued'
                    assert job.pending==1
            asyncio.run(main())
        ''')

    def test_floodwait_is_account_scoped(self):
        self._run(r'''
            import asyncio
            from app.db import AsyncSessionLocal
            from app.models import Account
            from app.tenant import set_tenant_id
            from app.tg_manager import manager

            async def main():
                set_tenant_id('00000000-0000-4000-8000-000000000102')
                async with AsyncSessionLocal() as db:
                    a=Account(phone='+10002',session_file='a',status='connected')
                    b=Account(phone='+10003',session_file='b',status='connected')
                    db.add_all([a,b]); await db.commit(); await db.refresh(a); await db.refresh(b)
                await manager.mark_flood_wait(a.id, 3)
                assert await manager.flood_wait_remaining(a.id) > 0
                assert await manager.flood_wait_remaining(b.id) == 0
                async with AsyncSessionLocal() as db:
                    aa=await db.get(Account,a.id); bb=await db.get(Account,b.id)
                    assert aa.status=='flood_wait' and aa.flood_wait_until is not None
                    assert bb.status=='connected' and bb.flood_wait_until is None
            asyncio.run(main())
        ''')

    def test_recovery_quarantines_inflight_item(self):
        self._run(r'''
            import asyncio
            from sqlalchemy import select
            from app.db import AsyncSessionLocal
            from app.message_dispatch_runner import create_message_job, message_dispatch_runner
            from app.models import Account, BulkJob, MessageDispatchItem
            from app.tenant import set_tenant_id

            async def main():
                set_tenant_id('00000000-0000-4000-8000-000000000103')
                async with AsyncSessionLocal() as db:
                    acc=Account(phone='+10004',session_file='a',status='connected')
                    db.add(acc); await db.commit(); await db.refresh(acc)
                job_id=await create_message_job([(acc.id,acc.phone,'A')],[('@a','user:a'),('@b','user:b')],'secret')
                async with AsyncSessionLocal() as db:
                    rows=(await db.execute(select(MessageDispatchItem).where(MessageDispatchItem.job_id==job_id).order_by(MessageDispatchItem.id))).scalars().all()
                    rows[0].status='processing'; rows[0].processing_token='tok'; job=await db.get(BulkJob,job_id); job.status='running'; await db.commit()
                await message_dispatch_runner.recover_stale()
                async with AsyncSessionLocal() as db:
                    rows=(await db.execute(select(MessageDispatchItem).where(MessageDispatchItem.job_id==job_id).order_by(MessageDispatchItem.id))).scalars().all()
                    job=await db.get(BulkJob,job_id)
                    assert rows[0].status=='in_flight_unknown' and rows[0].processing_token is None
                    assert rows[1].status=='queued' and job.status=='queued'
            asyncio.run(main())
        ''')

    def test_pause_resume_and_encrypted_payload(self):
        self._run(r'''
            import asyncio
            from sqlalchemy import select
            from app import job_store, secrets_store
            from app.db import AsyncSessionLocal
            from app.message_dispatch_runner import create_message_job, _secret_name
            from app.models import Account, BulkJob, EncryptedSecret
            from app.tenant import set_tenant_id

            async def main():
                uid='00000000-0000-4000-8000-000000000104'; set_tenant_id(uid)
                async with AsyncSessionLocal() as db:
                    acc=Account(phone='+10005',session_file='a',status='connected')
                    db.add(acc); await db.commit(); await db.refresh(acc)
                text='payload-must-stay-encrypted'
                job_id=await create_message_job([(acc.id,acc.phone,'A')],[('@a','user:a')],text)
                assert await job_store.pause_job(job_id)
                assert await job_store.resume_job(job_id)
                async with AsyncSessionLocal() as db:
                    job=await db.get(BulkJob,job_id)
                    row=(await db.execute(select(EncryptedSecret))).scalars().one()
                    assert job.status=='queued' and job.resume_count==1 and job.paused_at is None
                    assert text not in str(job.parameters) and text not in row.ciphertext
                assert await secrets_store.get_named_secret(_secret_name(job_id),uid)==text
            asyncio.run(main())
        ''')


if __name__ == '__main__':
    unittest.main()
