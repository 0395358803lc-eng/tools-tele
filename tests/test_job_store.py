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
VENV_PYTHON = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


class JobStoreTests(unittest.TestCase):
    def test_persistence_cancel_and_stale_recovery(self):
        with tempfile.TemporaryDirectory(prefix='mtm_job_test_') as td:
            db_path = Path(td) / 'jobs.db'
            env = os.environ.copy()
            env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
            env['DATABASE_URL'] = ''
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent('''
                import asyncio
                from datetime import datetime, timedelta
                from sqlalchemy import select
                from app import job_store
                from app.db import AsyncSessionLocal
                from app.models import Account, BulkJob

                async def main():
                    async with AsyncSessionLocal() as db:
                        a = Account(phone='job-test', session_file='x', status='connected')
                        db.add(a); await db.commit(); await db.refresh(a)
                        aid = a.id

                    jid = await job_store.create_job('integration', [(aid, 'job-test', 'Job Test')])
                    async with AsyncSessionLocal() as db:
                        job = await db.get(BulkJob, jid)
                        assert job.runner_id == job_store.RUNNER_ID
                        assert job.heartbeat_at is not None

                    assert await job_store.request_cancel(jid)
                    job_store._cancel_events.clear()
                    assert await job_store.is_cancelled(jid) is True
                    await job_store.finish_job(jid, 'cancelled', success=0, failed=0, skipped=1, pending=0)

                    stale = await job_store.create_job('stale', [(aid, 'job-test', 'Job Test')])
                    async with AsyncSessionLocal() as db:
                        job = await db.get(BulkJob, stale)
                        job.heartbeat_at = datetime.now() - timedelta(seconds=1000)
                        await db.commit()
                    recovered = await job_store.recover_interrupted_jobs(stale_after_seconds=30)
                    async with AsyncSessionLocal() as db:
                        job = await db.get(BulkJob, stale)
                        assert job.status == 'interrupted'
                    assert recovered == 1

                asyncio.run(main())
            ''')
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_bulk_action_timeout_is_persisted(self):
        with tempfile.TemporaryDirectory(prefix='mtm_bulk_timeout_') as td:
            db_path = Path(td) / 'timeout.db'
            env = os.environ.copy()
            env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
            env['DATABASE_URL'] = ''
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio, json
                from sqlalchemy import select
                from app.config import settings
                from app.db import AsyncSessionLocal
                from app.models import Account, BulkJob, BulkJobItem
                from app.tg_manager import manager
                from app.utils import bulk_stream

                async def main():
                    async with AsyncSessionLocal() as db:
                        a=Account(phone='timeout-test',session_file='x',status='connected')
                        db.add(a); await db.commit(); await db.refresh(a); aid=a.id
                    manager._clients[aid]=object()
                    settings.RATE_MIN=0; settings.RATE_MAX=0; settings.TG_RPC_TIMEOUT_SECONDS=0.1
                    async def slow(_cli,_aid):
                        await asyncio.sleep(0.3)
                        return 'ok','late'
                    events=[]
                    async for chunk in bulk_stream([(aid,'timeout-test','Timeout Test')],slow,job_type='timeout_test'):
                        events.append(json.loads(chunk))
                    done=[e for e in events if e.get('type')=='done'][-1]
                    assert done['failed']==1 and done['success']==0
                    async with AsyncSessionLocal() as db:
                        item=(await db.execute(select(BulkJobItem))).scalar_one()
                        assert item.status=='failed' and item.error_code=='TimeoutError'
                    manager._clients.pop(aid,None)
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_job_parameter_redaction_and_safe_retry(self):
        with tempfile.TemporaryDirectory(prefix='mtm_job_retry_') as td:
            db_path = Path(td) / 'retry.db'
            env = os.environ.copy()
            env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
            env['DATABASE_URL'] = ''
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio, json
                from fastapi import HTTPException
                from sqlalchemy import select
                from app import job_store
                from app.db import AsyncSessionLocal
                from app.models import Account, BulkJob
                from app.routers.jobs import retry_job

                async def consume(response):
                    events=[]
                    async for chunk in response.body_iterator:
                        if isinstance(chunk, bytes): chunk=chunk.decode()
                        for line in str(chunk).splitlines():
                            if line.strip(): events.append(json.loads(line))
                    return events

                async def main():
                    async with AsyncSessionLocal() as db:
                        a=Account(phone='retry-test',session_file='x',status='connected')
                        db.add(a); await db.commit(); await db.refresh(a); aid=a.id

                    source = await job_store.create_job(
                        'group_join', [(aid,'retry-test','Retry Test')],
                        {'target':'@retry_target','message_text':'secret-message','password':'secret-password'},
                    )
                    await job_store.mark_item_started(source, aid)
                    await job_store.mark_item_result(source, aid, 'failed', 'temporary failure', 'TimeoutError')
                    await job_store.finish_job(source, 'completed_with_errors', success=0, failed=1, skipped=0, pending=0)

                    async with AsyncSessionLocal() as db:
                        source_row=await db.get(BulkJob, source)
                        assert source_row.parameters['target']=='@retry_target'
                        assert source_row.parameters['message_text']=='[redacted]'
                        assert source_row.parameters['password']=='[redacted]'
                        response=await retry_job(source, db)
                    events=await consume(response)
                    done=[e for e in events if e.get('type')=='done'][-1]
                    retry_id=done['job_id']
                    assert retry_id != source
                    async with AsyncSessionLocal() as db:
                        retry_row=await db.get(BulkJob,retry_id)
                        assert retry_row.parameters['retry_of']==source
                        assert retry_row.parameters['target']=='@retry_target'

                    unsafe=await job_store.create_job('message_send',[(aid,'retry-test','Retry Test')],{'target':'@x','text':'do not persist'})
                    await job_store.mark_item_started(unsafe,aid)
                    await job_store.mark_item_result(unsafe,aid,'failed','failed','X')
                    await job_store.finish_job(unsafe,'completed_with_errors',success=0,failed=1,skipped=0,pending=0)
                    async with AsyncSessionLocal() as db:
                        row=await db.get(BulkJob,unsafe)
                        assert row.parameters['text']=='[redacted]'
                        try:
                            await retry_job(unsafe,db)
                        except HTTPException as exc:
                            assert exc.status_code==400
                        else:
                            raise AssertionError('unsafe job retry should fail')

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
