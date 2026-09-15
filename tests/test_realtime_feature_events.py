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


class RealtimeFeatureEventTests(unittest.TestCase):
    def _run(self, code: str):
        with tempfile.TemporaryDirectory(prefix="mtm_feature_events_") as td:
            db_path = Path(td) / "events.db"
            env = os.environ.copy()
            env["DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
            env["DATABASE_URL"] = ""
            env["SESSIONS_DIR"] = str(Path(td) / "sessions")
            subprocess.run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([PYTHON, "-c", textwrap.dedent(code)], cwd=BACKEND, env=env, check=True)
    def test_account_proxy_and_job_transitions_emit_once(self):
        self._run(r'''
            import asyncio
            from datetime import timedelta
            from sqlalchemy import select
            from app.db import AsyncSessionLocal
            from app.models import Account, AccountProxy, BulkJob
            from app.tenant import tenant_scope
            from app.time_utils import utcnow
            from app.tg_manager import manager
            from app.proxy_store import mark_proxy_status
            from app import job_store
            from app.realtime_events import query_events

            UID='77777777-7777-4777-8777-777777777777'

            async def main():
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        acc=Account(user_id=UID, phone='+84900000001', session_file='a.session', status='disconnected')
                        db.add(acc); await db.flush()
                        aid=acc.id
                        db.add(AccountProxy(user_id=UID, account_id=aid, enabled=True, proxy_type='socks5', host='127.0.0.1', port=1080, last_status='pending'))
                        db.add(BulkJob(user_id=UID, id='job-feature-test', type='phone_check', status='running', total=1, success=0, failed=0, skipped=0, pending=1, created_at=utcnow(), heartbeat_at=utcnow(), updated_at=utcnow()))
                        await db.commit()

                    await manager._set_status(aid, 'connecting')
                    await manager._set_status(aid, 'connecting')
                    await manager._set_status(aid, 'connected')
                    await manager.mark_flood_wait(aid, 2)
                    async with AsyncSessionLocal() as db:
                        row=await db.get(Account, aid)
                        row.flood_wait_until=utcnow()-timedelta(seconds=1)
                        await db.commit()
                    assert await manager.flood_wait_remaining(aid) == 0

                    await mark_proxy_status(aid, 'test_ok')
                    await mark_proxy_status(aid, 'test_ok')
                    assert await job_store.pause_job('job-feature-test')
                    assert await job_store.resume_job('job-feature-test')
                    assert await job_store.fail_job('job-feature-test', 'TEST_ERROR', 'secret-token-should-not-be-logged')

                accounts=await query_events(UID, feature='accounts', limit=50, ascending=True)
                phases=[r['phase'] for r in accounts]
                assert phases.count('connecting') == 1, phases
                assert 'connected' in phases and 'flood_wait' in phases and 'flood_wait_cleared' in phases
                proxy=await query_events(UID, feature='proxy', limit=20)
                assert [r['phase'] for r in proxy].count('test_ok') == 1
                jobs=await query_events(UID, feature='jobs', job_id='job-feature-test', limit=20, ascending=True)
                assert [r['phase'] for r in jobs] == ['paused','resumed','failed']
                assert all('secret-token' not in (r['message'] or '') for r in jobs)
            asyncio.run(main())
        ''')
    def test_feature_modules_emit_expected_milestones(self):
        files = {
            'backend/app/message_dispatch_runner.py': ['job_created', 'worker_started', 'flood_wait', 'job_finished'],
            'backend/app/phone_check_runner.py': ['worker_started', 'job_finished', 'phone_check'],
            'backend/app/routers/phone_checks.py': ['job_created', 'phone_numbers', 'phone_check_csv'],
            'backend/app/routers/inbox.py': ['reply_started', 'reply_sent', 'reply_failed', 'reply_unknown', 'marked_read'],
            'backend/app/routers/messaging.py': ['message_targets'],
            'backend/app/routers/jobs.py': ['job_csv', 'job_xlsx'],
            'backend/app/routers/proxies.py': ['test_started', 'test_ok', 'test_failed'],
            'backend/app/tg_manager.py': ['new_message', 'flood_wait_cleared'],
        }
        for rel, markers in files.items():
            source = (ROOT / rel).read_text(encoding='utf-8')
            self.assertIn('emit_event', source, rel)
            for marker in markers:
                self.assertIn(marker, source, f'{rel}: {marker}')


if __name__ == '__main__':
    unittest.main()
