from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
PYTHON = sys.executable


class ObservabilityRetentionTests(unittest.TestCase):
    def test_log_redaction_and_rotation_contract(self):
        from backend.app.logging_config import redact_text
        sample = 'DATABASE_URL=postgresql://postgres:VerySecret@host/db token=abc123 Authorization=BearerXYZ'
        clean = redact_text(sample)
        self.assertNotIn('VerySecret', clean)
        self.assertNotIn('abc123', clean)
        self.assertNotIn('BearerXYZ', clean)
        source = (BACKEND / 'app' / 'logging_config.py').read_text(encoding='utf-8')
        self.assertIn('RotatingFileHandler', source)
        self.assertIn("backend.jsonl", source)

    def test_request_metrics_counters(self):
        from backend.app import runtime_metrics as metrics
        before = metrics.snapshot()
        metrics.observe_request(200, 10)
        metrics.observe_request(404, 20)
        metrics.observe_request(500, 30)
        after = metrics.snapshot()
        self.assertEqual(after['requests_total'] - before['requests_total'], 3)
        self.assertEqual(after['requests_4xx'] - before['requests_4xx'], 1)
        self.assertEqual(after['requests_5xx'] - before['requests_5xx'], 1)
        self.assertGreaterEqual(after['request_duration_p95_ms'], 0)

    def test_alert_history_deduplicates_state_transitions(self):
        from backend.app import ops_alerts
        with tempfile.TemporaryDirectory() as td:
            old = (ops_alerts.LOG_DIR, ops_alerts.STATE_FILE, ops_alerts.ALERT_FILE)
            logger = logging.getLogger('ops_alert_events')
            old_handlers = list(logger.handlers)
            try:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()
                base = Path(td)
                ops_alerts.LOG_DIR = base
                ops_alerts.STATE_FILE = base / 'state.json'
                ops_alerts.ALERT_FILE = base / 'alerts.jsonl'
                self.assertTrue(ops_alerts.set_alert('db', True, message='down', source='test'))
                self.assertFalse(ops_alerts.set_alert('db', True, message='down', source='test'))
                self.assertTrue(ops_alerts.set_alert('db', False, message='up', source='test'))
                rows = ops_alerts.recent_alerts(10)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]['status'], 'resolved')
                self.assertEqual(rows[1]['status'], 'opened')
            finally:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()
                ops_alerts.LOG_DIR, ops_alerts.STATE_FILE, ops_alerts.ALERT_FILE = old
                for handler in old_handlers:
                    logger.addHandler(handler)

    def test_maintenance_task_and_admin_ui_contract(self):
        installer = (ROOT / 'scripts' / 'install_windows_tasks.py').read_text(encoding='utf-8')
        self.assertIn('MTM_Maintenance', installer)
        self.assertIn('maintenance_cleanup.py', installer)
        self.assertIn('"04:15"', installer)
        ui = (ROOT / 'frontend' / 'src' / 'components' / 'AdminPage.jsx').read_text(encoding='utf-8')
        for token in ('P95 latency', 'HTTP 5xx', 'Lịch sử cảnh báo gần đây', 'Maintenance:'):
            self.assertIn(token, ui)

    def test_retention_dry_run_then_apply_keeps_recent_rows(self):
        with tempfile.TemporaryDirectory(prefix='mtm_retention_') as td:
            db_path = Path(td) / 'retention.db'
            env = os.environ.copy()
            env.update({
                'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': '',
                'NODE_ENV': 'development', 'RETENTION_AUDIT_DAYS': '180',
                'RETENTION_JOBS_DAYS': '90', 'RETENTION_LOGIN_DAYS': '30',
            })
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND,
                           env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = r'''
import asyncio
from datetime import timedelta
from sqlalchemy import func, select
from scripts import maintenance_cleanup as mc
from backend.app.db import AsyncSessionLocal
from backend.app.models import AuditLog, BulkJob, LoginAttempt
from backend.app.tenant import system_scope, tenant_scope
from backend.app.time_utils import utcnow

async def main():
    uid='00000000-0000-4000-8000-000000000029'
    now=utcnow(); old=now-timedelta(days=400)
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            db.add_all([AuditLog(user_id=uid,action='old',created_at=old), AuditLog(user_id=uid,action='new',created_at=now)])
            db.add_all([BulkJob(id='old-job',user_id=uid,type='x',status='completed',created_at=old), BulkJob(id='new-job',user_id=uid,type='x',status='completed',created_at=now)])
            await db.commit()
    with system_scope():
        async with AsyncSessionLocal() as db:
            db.add_all([LoginAttempt(ip='1',success=False,attempted_at=old), LoginAttempt(ip='2',success=True,attempted_at=now)])
            await db.commit()
    dry=await mc.cleanup(False)
    assert dry['audit_logs']==1 and dry['bulk_jobs']==1 and dry['login_attempts']==1
    applied=await mc.cleanup(True)
    assert applied['audit_logs']==1 and applied['bulk_jobs']==1 and applied['login_attempts']==1
    with system_scope():
        async with AsyncSessionLocal() as db:
            assert await db.scalar(select(func.count(AuditLog.id))) == 1
            assert await db.scalar(select(func.count(BulkJob.id))) == 1
            assert await db.scalar(select(func.count(LoginAttempt.id))) == 1
asyncio.run(main())
'''
            subprocess.run([PYTHON, '-c', code], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
