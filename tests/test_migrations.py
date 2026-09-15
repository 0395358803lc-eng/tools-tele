from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT.parents[1]
VENV_PYTHON = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


class MigrationTests(unittest.TestCase):
    def test_fresh_database_reaches_head_with_bigint_ids(self):
        with tempfile.TemporaryDirectory(prefix='mtm_migration_test_') as td:
            db_path = Path(td) / 'fresh.db'
            env = os.environ.copy()
            env['DB_URL'] = f'sqlite+aiosqlite:///{db_path}'
            env['DATABASE_URL'] = ''
            subprocess.run(
                [PYTHON, '-m', 'alembic', 'upgrade', 'head'],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            db = sqlite3.connect(db_path)
            try:
                revision = db.execute('select version_num from alembic_version').fetchone()[0]
                self.assertEqual(revision, '8a4b5c6d7e8f')
                for table, col in [
                    ('accounts', 'tg_user_id'),
                    ('gone_accounts', 'tg_user_id'),
                    ('security_messages', 'tg_msg_id'),
                ]:
                    typ = [r[2] for r in db.execute(f'pragma table_info({table})') if r[1] == col][0]
                    self.assertEqual(typ.upper(), 'BIGINT')

                account_cols = {r[1] for r in db.execute('pragma table_info(accounts)')}
                self.assertNotIn('is_online', account_cols)
                self.assertNotIn('last_seen', account_cols)
                tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
                self.assertNotIn('pending_logins', tables)
                job_cols = {r[1] for r in db.execute('pragma table_info(bulk_jobs)')}
                self.assertIn('runner_id', job_cols)
                self.assertIn('heartbeat_at', job_cols)
                tg_session_cols = {r[1] for r in db.execute('pragma table_info(telegram_sessions)')}
                self.assertIn('session_ciphertext', tg_session_cols)
                self.assertIn('encrypted_secrets', tables)
                self.assertIn('message_dispatch_items', tables)
                self.assertIn('realtime_events', tables)
                self.assertIn('account_proxies', tables)
                proxy_cols = {r[1] for r in db.execute('pragma table_info(account_proxies)')}
                for col in ('fallback_enabled', 'fallback_host', 'active_slot', 'failover_count', 'last_failover_at'):
                    self.assertIn(col, proxy_cols)
            finally:
                db.close()

    def test_postgres_migration_normalizes_sqlite_types(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mtm_pg_migrate", ROOT / "scripts" / "migrate_sqlite_to_postgres.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = module.normalize_row("bulk_jobs", {
            "parameters": "{\"x\": 1}",
            "created_at": "2026-09-10 01:02:03",
            "started_at": None,
        })
        self.assertEqual(row["parameters"], {"x": 1})
        self.assertEqual(row["created_at"].year, 2026)
        account = module.normalize_row("accounts", {"has_2fa": 1, "created_at": "2026-09-10"})
        self.assertIs(account["has_2fa"], True)
        self.assertEqual(account["created_at"].year, 2026)


if __name__ == '__main__':
    unittest.main()
