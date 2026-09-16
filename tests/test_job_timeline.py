from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class JobTimelineTests(unittest.TestCase):
    def _run_db(self, code: str):
        with tempfile.TemporaryDirectory(prefix='mtm_timeline_') as td:
            db_path = Path(td) / 'timeline.db'
            env = os.environ.copy()
            env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': '',
                        'SESSIONS_DIR': str(Path(td) / 'sessions')})
            subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                cwd=ROOT / 'backend', env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([sys.executable, '-c', textwrap.dedent(code)],
                cwd=ROOT / 'backend', env=env, check=True)

    def test_worker_lanes_stats_and_retry_countdown(self):
        self._run_db("""
            import asyncio
            from datetime import timedelta
            from app.db import AsyncSessionLocal
            from app.job_timeline import build_job_timeline
            from app.models import Account, BulkJob, MessageDispatchItem, RealtimeEvent
            from app.tenant import tenant_scope
            from app.time_utils import utcnow
            U='00000000-0000-4000-8000-000000000201'
            async def main():
                now=utcnow(); retry=now+timedelta(seconds=45)
                with tenant_scope(U):
                    async with AsyncSessionLocal() as db:
                        job=BulkJob(user_id=U,id='msg-job',type='message_multi_send',status='running',
                            total=3,success=1,failed=0,pending=2,created_at=now-timedelta(minutes=2),
                            started_at=now-timedelta(minutes=1),runner_id='runner-abc',heartbeat_at=now-timedelta(seconds=5))
                        db.add(job)
                        db.add_all([Account(user_id=U,phone='+1201',session_file='a'), Account(user_id=U,phone='+1202',session_file='b')])
                        await db.flush()
                        db.add_all([
                            MessageDispatchItem(user_id=U,job_id='msg-job',account_id=1,target='@a',normalized_target='a',status='ok',attempts=1),
                            MessageDispatchItem(user_id=U,job_id='msg-job',account_id=1,target='@b',normalized_target='b',status='rate_limited',attempts=1,next_retry_at=retry),
                            MessageDispatchItem(user_id=U,job_id='msg-job',account_id=2,target='@c',normalized_target='c',status='processing',attempts=1),
                        ])
                        db.add(RealtimeEvent(user_id=U,feature='messaging',level='warning',phase='flood_wait',message='wait',job_id='msg-job',account_id=1,created_at=now))
                        await db.commit()
                        rows=[{'id':r.id,'account_id':r.account_id,'target':r.target,'status':r.status,'attempts':r.attempts,'next_retry_at':r.next_retry_at} for r in (await db.execute(__import__('sqlalchemy').select(MessageDispatchItem).where(MessageDispatchItem.job_id=='msg-job'))).scalars().all()]
                        out=await build_job_timeline(db,job,rows)
                assert out['worker']['active'] and out['worker']['runner_id']=='runner-abc'
                assert 0 <= out['worker']['heartbeat_age_seconds'] < 20
                assert out['retry']['waiting_items']==1 and 0 < out['retry']['countdown_seconds'] <= 45
                assert out['item_statistics']['total']==3 and out['item_statistics']['attempts']==3
                assert len(out['account_lanes'])==2
                lane1=next(x for x in out['account_lanes'] if x['account_id']==1)
                lane2=next(x for x in out['account_lanes'] if x['account_id']==2)
                assert lane1['status']=='flood_wait' and lane2['status']=='running'
            asyncio.run(main())
        """)

    def test_visual_lifecycle_and_recovery_contract(self):
        self._run_db("""
            import asyncio
            from datetime import timedelta
            from sqlalchemy import select
            from app.db import AsyncSessionLocal
            from app.job_timeline import build_job_timeline
            from app.models import BulkJob, RealtimeEvent
            from app.tenant import tenant_scope
            from app.time_utils import utcnow
            U='00000000-0000-4000-8000-000000000202'
            async def main():
                now=utcnow()
                with tenant_scope(U):
                    async with AsyncSessionLocal() as db:
                        job=BulkJob(user_id=U,id='life-job',type='phone_check',status='completed',
                            total=1,success=1,pending=0,created_at=now-timedelta(minutes=8),
                            started_at=now-timedelta(minutes=7),finished_at=now,heartbeat_at=now)
                        db.add(job)
                        phases=['job_created','worker_started','flood_wait','temporary_error','job_paused','resumed','recovered','job_finished']
                        for i,phase in enumerate(phases):
                            db.add(RealtimeEvent(user_id=U,feature='phone_check',level='info',phase=phase,
                                message=phase,job_id='life-job',created_at=now-timedelta(minutes=7-i)))
                        await db.commit()
                        out=await build_job_timeline(db,job,[])
                kinds={x['kind'] for x in out['timeline']}
                for expected in ('created','queued','running','flood_wait','retry','paused','resume','recovery','completed'):
                    assert expected in kinds, (expected,kinds)
            asyncio.run(main())
        """)

    def test_frontend_and_recovery_event_sources(self):
        panel=(ROOT/'frontend/src/components/JobTimelinePanel.jsx').read_text(encoding='utf-8')
        jobs=(ROOT/'frontend/src/tabs/JobsTab.jsx').read_text(encoding='utf-8')
        routes=(ROOT/'backend/app/routers/jobs.py').read_text(encoding='utf-8')
        message=(ROOT/'backend/app/message_dispatch_runner.py').read_text(encoding='utf-8')
        phone=(ROOT/'backend/app/phone_check_runner.py').read_text(encoding='utf-8')
        store=(ROOT/'backend/app/job_store.py').read_text(encoding='utf-8')
        for label in ('Job Timeline','Account lanes','Item statistics','Current worker','Heartbeat age','Retry countdown'):
            self.assertIn(label,panel)
        for stage in ('FloodWait','Retry','Pause','Resume','Recovery','Completed'):
            self.assertIn(stage,panel)
        self.assertIn('<JobTimelinePanel job={selected} />',jobs)
        self.assertIn('build_job_timeline',routes)
        self.assertIn('"recovered"',message)
        self.assertIn('"recovered"',phone)
        self.assertIn('"recovery_interrupted"',store)


if __name__ == '__main__':
    unittest.main()
