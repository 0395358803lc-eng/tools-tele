from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


class ProductionActivationTests(unittest.TestCase):
    def test_activation_fails_closed_without_postgres_url(self):
        env = os.environ.copy()
        env['DATABASE_URL'] = ''
        env['DB_URL'] = 'sqlite+aiosqlite:///./app.db'
        proc = subprocess.run(
            [PYTHON, str(ROOT / 'scripts' / 'activate_production_database.py')],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        output = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('DATABASE_URL', output)
        self.assertIn('PostgreSQL', output)
        self.assertNotIn('APP_PASSWORD=', output)
        self.assertNotIn('SECRETS_ENCRYPTION_KEY=', output)
        self.assertNotIn('TG_API_HASH=', output)

    def test_activation_script_masks_database_urls_in_logged_commands(self):
        source = (ROOT / 'scripts' / 'activate_production_database.py').read_text(encoding='utf-8')
        self.assertIn("else '<DATABASE_URL>'", source)
        self.assertIn("--copy-sqlite", source)
        self.assertIn("DATA_COUNT_VERIFY_OK", source)
        self.assertIn("PRODUCTION_DATABASE_ACTIVATION_OK", source)


if __name__ == '__main__':
    unittest.main()
