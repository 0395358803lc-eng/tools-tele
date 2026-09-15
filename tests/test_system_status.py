from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from cryptography.fernet import Fernet
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT.parents[1]
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


class SystemStatusTests(unittest.TestCase):
    def test_readiness_matches_alembic_head(self):
        with tempfile.TemporaryDirectory(prefix='mtm_system_test_') as td:
            db_path = Path(td) / 'system.db'
            env = os.environ.copy()
            env.update({
                'DB_URL': f'sqlite+aiosqlite:///{db_path}',
                'DATABASE_URL': '',
                'TG_API_ID': '12345',
                'TG_API_HASH': '0123456789abcdef0123456789abcdef',
                'APP_PASSWORD': 'test-password-strong',
                'SECRETS_ENCRYPTION_KEY': Fernet.generate_key().decode(),
                'SUPABASE_URL': 'https://example.supabase.co',
                'SUPABASE_PUBLISHABLE_KEY': 'test-publishable-key',
                'SUPABASE_SECRET_KEY': 'test-secret-key',
                'NODE_ENV': 'development',
            })
            subprocess.run(
                [PYTHON, '-m', 'alembic', 'upgrade', 'head'],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            code = textwrap.dedent("""
                import asyncio
                from app.system_status import readiness, operational_status

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    ready = await readiness()
                    assert ready['ok'] is True
                    assert ready['db_revision'] == ready['expected_revision']
                    status = await operational_status()
                    assert status['db_revision'] == status['expected_revision']
                    assert status['account_total'] == 0
                    assert status['active_jobs'] == 0

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_metrics_render_without_sensitive_fields(self):
        with tempfile.TemporaryDirectory(prefix='mtm_metrics_test_') as td:
            db_path = Path(td) / 'metrics.db'
            env = os.environ.copy()
            env.update({
                'DB_URL': f'sqlite+aiosqlite:///{db_path}',
                'DATABASE_URL': '',
                'APP_PASSWORD': 'test-password-strong',
                'TG_API_ID': '12345',
                'TG_API_HASH': '0123456789abcdef0123456789abcdef',
                'SECRETS_ENCRYPTION_KEY': Fernet.generate_key().decode(),
            })
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from app.routers.system import system_metrics
                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    body = await system_metrics()
                    assert 'mtm_uptime_seconds ' in body
                    assert 'mtm_accounts_total 0' in body
                    assert 'password' not in body.lower()
                    assert 'token' not in body.lower()
                    assert 'message_text' not in body.lower()
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_production_sqlite_is_not_ready(self):
        with tempfile.TemporaryDirectory(prefix='mtm_system_prod_') as td:
            db_path = Path(td) / 'system.db'
            env = os.environ.copy()
            env.update({
                'DB_URL': f'sqlite+aiosqlite:///{db_path}',
                'DATABASE_URL': '',
                'TG_API_ID': '12345',
                'TG_API_HASH': '0123456789abcdef0123456789abcdef',
                'APP_PASSWORD': 'test-password-strong',
                'SECRETS_ENCRYPTION_KEY': Fernet.generate_key().decode(),
                'NODE_ENV': 'production',
            })
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from app.system_status import readiness
                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    ready = await readiness()
                    assert ready['ok'] is False
                    assert ready['persistent_storage'] is False
                    assert 'persistent_storage' in ready['failed_checks']
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
