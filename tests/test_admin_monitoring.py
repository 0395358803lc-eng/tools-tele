from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from starlette.requests import Request

from app import quota
from app.config import settings
from app.security_middleware import _RATE_BUCKETS, _rate_limit
import app.supabase_identity as identity


class AdminMonitoringTests(unittest.TestCase):
    def test_quota_normalization_clamps_and_defaults(self):
        value = quota.normalize_quotas({'max_accounts': -5, 'max_proxies': '7'})
        self.assertEqual(value['max_accounts'], 0)
        self.assertEqual(value['max_proxies'], 7)
        self.assertEqual(value['max_active_jobs'], quota.DEFAULT_QUOTAS['max_active_jobs'])
    def test_admin_rate_limit_bucket(self):
        scope = {
            'type': 'http', 'method': 'GET', 'path': '/api/admin/health',
            'raw_path': b'/api/admin/health', 'query_string': b'',
            'headers': [], 'client': ('127.0.0.1', 12345),
            'server': ('testserver', 80), 'scheme': 'http',
        }
        request = Request(scope)
        _RATE_BUCKETS.clear()
        with patch.object(settings, 'ADMIN_RATE_LIMIT_PER_MIN', 2), patch.object(settings, 'TRUST_PROXY_HEADERS', False):
            self.assertEqual(_rate_limit(request), (True, 0))
            self.assertEqual(_rate_limit(request), (True, 0))
            allowed, retry = _rate_limit(request)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)

    def test_force_logout_preserves_role_and_quota(self):
        user = SimpleNamespace(
            id='u1', email='u1@example.net', user_metadata={'username': 'u1'},
            app_metadata={'role': 'user', 'quotas': {'max_accounts': 9}},
            banned_until=None, created_at=None, last_sign_in_at=None,
        )
        captured = {}
        class Admin:
            def get_user_by_id(self, uid):
                self_uid = uid
                return SimpleNamespace(user=user)
            def update_user_by_id(self, uid, attrs):
                captured.update(attrs)
                if 'app_metadata' in attrs:
                    user.app_metadata = attrs['app_metadata']
                return SimpleNamespace(user=user)

        client = SimpleNamespace(auth=SimpleNamespace(admin=Admin()))
        with patch.object(identity, '_server_client', return_value=client):
            out = identity.force_logout_identity_user('u1')
        self.assertEqual(out.role, 'user')
        self.assertEqual(out.quotas['max_accounts'], 9)
        self.assertTrue(out.session_not_before)
        self.assertIn('session_not_before', captured['app_metadata'])

    def test_admin_frontend_contract(self):
        source = (ROOT / 'frontend' / 'src' / 'components' / 'AdminPage.jsx').read_text(encoding='utf-8')
        for expected in ('Force logout', 'Jobs toàn hệ thống', 'Audit toàn hệ thống', 'System Health', 'Lưu quota'):
            self.assertIn(expected, source)


    def test_admin_portal_is_separate_from_user_portal(self):
        app = (ROOT / 'frontend' / 'src' / 'App.jsx').read_text(encoding='utf-8')
        user_login = (ROOT / 'frontend' / 'src' / 'components' / 'LoginScreen.jsx').read_text(encoding='utf-8')
        admin_login = (ROOT / 'frontend' / 'src' / 'components' / 'AdminLoginScreen.jsx').read_text(encoding='utf-8')
        admin_page = (ROOT / 'frontend' / 'src' / 'components' / 'AdminPage.jsx').read_text(encoding='utf-8')
        supabase = (ROOT / 'frontend' / 'src' / 'lib' / 'supabase.js').read_text(encoding='utf-8')
        self.assertIn("const Login = adminRoute ? AdminLoginScreen : LoginScreen", app)
        self.assertIn("authState !== 'in' || adminRoute", app)
        self.assertNotIn("window.location.href = '/admin'", app)
        self.assertIn('USER PORTAL', user_login)
        self.assertNotIn('bootstrapAdmin', user_login)
        self.assertIn('ADMIN PORTAL', admin_login)
        self.assertIn('Tài khoản không có quyền ADMIN', admin_login)
        self.assertIn("signInIdentity(username, password, 'admin')", admin_login)
        self.assertIn("buildClient('mtm-user-auth')", supabase)
        self.assertIn("buildClient('mtm-admin-auth')", supabase)
        self.assertNotIn('onBack', admin_page)
        self.assertNotIn('>Ứng dụng</button>', admin_page)


    def test_hard_purge_is_tenant_scoped(self):
        with tempfile.TemporaryDirectory(prefix='mtm_purge_') as td:
            db_path = Path(td) / 'purge.db'
            env = os.environ.copy()
            env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': '', 'SESSIONS_DIR': str(Path(td) / 'sessions')})
            subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'backend', env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from sqlalchemy import func, select
                from app.admin_service import purge_tenant_data
                from app.db import AsyncSessionLocal
                from app.models import Account, BulkJob
                from app.tenant import system_scope
                A='00000000-0000-4000-8000-000000000001'; B='00000000-0000-4000-8000-000000000002'
                async def main():
                    with system_scope():
                        async with AsyncSessionLocal() as db:
                            db.add_all([Account(user_id=A,phone='+1001',session_file='a'), Account(user_id=B,phone='+1002',session_file='b')])
                            db.add_all([BulkJob(user_id=A,id='ja',type='x',status='completed'), BulkJob(user_id=B,id='jb',type='x',status='completed')])
                            await db.commit()
                    counts=await purge_tenant_data(A)
                    assert counts['accounts']==1 and counts['bulk_jobs']==1
                    with system_scope():
                        async with AsyncSessionLocal() as db:
                            assert await db.scalar(select(func.count(Account.id)).where(Account.user_id==A)) == 0
                            assert await db.scalar(select(func.count(Account.id)).where(Account.user_id==B)) == 1
                            assert await db.scalar(select(func.count(BulkJob.id)).where(BulkJob.user_id==B)) == 1
                asyncio.run(main())
            """)
            subprocess.run([sys.executable, '-c', code], cwd=ROOT / 'backend', env=env, check=True)


if __name__ == '__main__':
    unittest.main()
