from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT.parents[1]
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


class DatabaseConfigTests(unittest.TestCase):
    def test_sqlite_does_not_receive_postgres_pool_options(self):
        env = os.environ.copy()
        env.update({'DB_URL': 'sqlite+aiosqlite:////tmp/mtm_pool_sqlite.db', 'DATABASE_URL': ''})
        code = textwrap.dedent("""
            from app import db
            assert db._is_sqlite is True
            assert db._engine_kwargs['connect_args']['timeout'] == 30
            assert 'pool_size' not in db._engine_kwargs
            assert 'max_overflow' not in db._engine_kwargs
            assert 'pool_timeout' not in db._engine_kwargs
        """)
        subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_postgres_pool_options_are_bounded_and_applied(self):
        env = os.environ.copy()
        env.update({
            'DB_URL': 'sqlite+aiosqlite:////tmp/unused.db',
            'DATABASE_URL': 'postgresql://user:pass@127.0.0.1:1/mtm',
            'DB_POOL_SIZE': '7',
            'DB_MAX_OVERFLOW': '3',
            'DB_POOL_TIMEOUT_SECONDS': '17',
            'DB_POOL_RECYCLE_SECONDS': '901',
        })
        code = textwrap.dedent("""
            from app import db
            assert db._is_sqlite is False
            kw = db._engine_kwargs
            assert kw['pool_pre_ping'] is True
            assert kw['pool_size'] == 7
            assert kw['max_overflow'] == 3
            assert kw['pool_timeout'] == 17.0
            assert kw['pool_recycle'] == 901
            assert kw['pool_use_lifo'] is True
        """)
        subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_postgres_pool_options_are_clamped(self):
        env = os.environ.copy()
        env.update({
            'DATABASE_URL': 'postgresql://user:pass@127.0.0.1:1/mtm',
            'DB_POOL_SIZE': '999',
            'DB_MAX_OVERFLOW': '999',
            'DB_POOL_TIMEOUT_SECONDS': '999',
            'DB_POOL_RECYCLE_SECONDS': '1',
        })
        code = textwrap.dedent("""
            from app import db
            kw = db._engine_kwargs
            assert kw['pool_size'] == 50
            assert kw['max_overflow'] == 50
            assert kw['pool_timeout'] == 120.0
            assert kw['pool_recycle'] == 60
        """)
        subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
