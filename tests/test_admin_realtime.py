from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AdminRealtimeTests(unittest.TestCase):
    def _run_db(self, code: str):
        with tempfile.TemporaryDirectory(prefix='mtm_admin_rt_') as td:
            db_path = Path(td) / 'admin-rt.db'
            env = os.environ.copy()
            env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': '',
                        'SESSIONS_DIR': str(Path(td) / 'sessions')})
            subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                cwd=ROOT / 'backend', env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([sys.executable, '-c', textwrap.dedent(code)], cwd=ROOT / 'backend', env=env, check=True)

    def test_snapshot_filters_and_safe_drilldown(self):
        self._run_db("""
            import asyncio
            from datetime import timedelta
            from app.admin_realtime import realtime_events, realtime_snapshot, realtime_user_detail
            from app.db import AsyncSessionLocal
            from app.models import Account, AccountProxy, BulkJob, RealtimeEvent
            from app.tenant import system_scope
            from app.time_utils import utcnow
            U1='00000000-0000-4000-8000-000000000101'; U2='00000000-0000-4000-8000-000000000102'
            async def main():
                now=utcnow()
                with system_scope():
                    async with AsyncSessionLocal() as db:
                        db.add_all([
                            Account(user_id=U1,phone='+1001',session_file='a',status='connected',flood_wait_until=now+timedelta(minutes=3)),
                            Account(user_id=U2,phone='+1002',session_file='b',status='disconnected'),
                        ])
                        await db.flush()
                        db.add(AccountProxy(user_id=U1,account_id=1,host='127.0.0.1',port=1080,last_status='failed'))
                        db.add_all([
                            BulkJob(user_id=U1,id='job-a',type='message_multi_send',status='running',total=10,success=4,failed=1,pending=5),
                            BulkJob(user_id=U2,id='job-b',type='phone_check',status='failed',total=2,failed=2,pending=0),
                        ])
                        db.add_all([
                            RealtimeEvent(user_id=U1,feature='proxy',level='error',phase='test_failed',message='Proxy test failed',account_id=1,job_id='job-a',metadata_json={'proxy_password':'secret','latency_ms':80},created_at=now),
                            RealtimeEvent(user_id=U2,feature='job',level='info',phase='created',message='Job created',job_id='job-b',created_at=now),
                        ])
                        await db.commit()
                snap=await realtime_snapshot()
                assert snap['active_users'] == 2 and snap['connected_accounts'] == 1
                assert snap['flood_wait'] == 1 and snap['proxy_failures'] == 1
                assert snap['active_jobs'] == 1 and snap['failed_jobs'] == 1 and snap['queue_depth'] == 5
                rows=await realtime_events(user_id=U1, feature='proxy', level='error', account_id=1, job_id='job-a')
                assert len(rows)==1 and rows[0]['metadata']['proxy_password']=='[redacted]'
                detail=await realtime_user_detail(U1)
                assert detail['accounts'][0]['proxy']['last_status']=='failed'
                assert 'session_file' not in detail['accounts'][0] and 'last_error' not in detail['accounts'][0]
            asyncio.run(main())
        """)

    def test_admin_realtime_ui_and_audit_contract(self):
        page = (ROOT / 'frontend/src/components/AdminPage.jsx').read_text(encoding='utf-8')
        monitor = (ROOT / 'frontend/src/components/AdminRealtimeMonitor.jsx').read_text(encoding='utf-8')
        routes = (ROOT / 'backend/app/routers/admin.py').read_text(encoding='utf-8')
        service = (ROOT / 'backend/app/admin_realtime.py').read_text(encoding='utf-8')
        self.assertIn("['realtime', 'Realtime']", page)
        for expected in ('Active users', 'FloodWait', 'Proxy fail', 'Queue depth', 'Events/min', 'Timeline vận hành'):
            self.assertIn(expected, monitor)
        for expected in ('user_id', 'feature', 'level', 'account_id', 'job_id'):
            self.assertIn(expected, monitor)
        self.assertIn('admin:realtime_user_view', routes)
        self.assertIn('admin:realtime_events_view', routes)
        self.assertNotIn('session_ciphertext', service)
        self.assertNotIn('password_ciphertext', service)
        self.assertNotIn('api_hash', service)
        self.assertNotIn('message_text', service)


if __name__ == '__main__':
    unittest.main()
