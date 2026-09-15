from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import backup_runtime as br
from scripts import restore_runtime as rr

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
VENV_PYTHON = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


class BackupRestoreTests(unittest.TestCase):
    def test_sqlite_and_session_round_trip(self):
        with tempfile.TemporaryDirectory(prefix='mtm_backup_test_') as td:
            base = Path(td)
            src = base / 'src'
            dst = base / 'dst'
            archive = base / 'runtime.tar.gz'
            (src / 'backend' / 'sessions').mkdir(parents=True)
            dst.mkdir()
            (src / 'backend' / '.env').write_text(
                'DB_URL=sqlite+aiosqlite:///./app.db\nSESSIONS_DIR=./sessions\nAPP_PASSWORD=test-only\n',
                encoding='utf-8',
            )
            for path, value in [
                (src / 'backend' / 'app.db', 'main-ok'),
                (src / 'backend' / 'sessions' / 'acc_test.session', 'session-ok'),
            ]:
                db = sqlite3.connect(path)
                db.execute('create table t(v text)')
                db.execute('insert into t values(?)', (value,))
                db.commit(); db.close()
            (src / 'backend' / 'sessions' / 'twofa.enc').write_bytes(b'encrypted-dummy')

            subprocess.run([PYTHON, str(ROOT / 'scripts' / 'backup_runtime.py'), '--project-root', str(src), '--output', str(archive), '--include-env'], check=True, stdout=subprocess.PIPE)
            subprocess.run([PYTHON, str(ROOT / 'scripts' / 'restore_runtime.py'), str(archive), '--project-root', str(dst), '--verify-only'], check=True, stdout=subprocess.PIPE)
            subprocess.run([PYTHON, str(ROOT / 'scripts' / 'restore_runtime.py'), str(archive), '--project-root', str(dst), '--force', '--restore-env'], check=True, stdout=subprocess.PIPE)

            db = sqlite3.connect(dst / 'backend' / 'app.db')
            self.assertEqual(db.execute('select v from t').fetchone()[0], 'main-ok')
            db.close()
            db = sqlite3.connect(dst / 'backend' / 'sessions' / 'acc_test.session')
            self.assertEqual(db.execute('select v from t').fetchone()[0], 'session-ok')
            db.close()
            self.assertEqual((dst / 'backend' / 'sessions' / 'twofa.enc').read_bytes(), b'encrypted-dummy')
            self.assertIn('test-only', (dst / 'backend' / '.env').read_text(encoding='utf-8'))
            if os.name != 'nt':
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)


    def test_pg_tool_discovery_uses_project_user_home(self):
        with tempfile.TemporaryDirectory(prefix='mtm_pg_tool_') as td:
            base = Path(td)
            project = base / 'Users' / 'Admin' / 'Downloads' / 'tools-tele'
            runtime = base / 'Users' / 'Admin' / 'AppData' / 'Local' / 'Programs' / 'pgAdmin 4' / 'runtime'
            project.mkdir(parents=True)
            runtime.mkdir(parents=True)
            exe = 'pg_dump.exe' if os.name == 'nt' else 'pg_dump'
            tool = runtime / exe
            tool.write_bytes(b'test')
            with mock.patch.object(br.shutil, 'which', return_value=None), \
                 mock.patch.dict(os.environ, {'LOCALAPPDATA': '', 'ProgramFiles': '', 'SystemDrive': ''}, clear=False):
                self.assertTrue(br.find_pg_tool('pg_dump', project).samefile(tool))
                self.assertTrue(rr.find_pg_tool('pg_dump', project).samefile(tool))

    def test_nested_tenant_session_and_encryption_key_round_trip(self):
        with tempfile.TemporaryDirectory(prefix='mtm_nested_backup_') as td:
            base = Path(td); src = base/'src'; dst = base/'dst'; archive = base/'runtime.tar.gz'
            sessions = src/'backend'/'sessions'; tenant = sessions/'user_test'; tenant.mkdir(parents=True)
            dst.mkdir()
            (src/'backend'/'.env').write_text('DB_URL=sqlite+aiosqlite:///./app.db\nSESSIONS_DIR=./sessions\n', encoding='utf-8')
            for path, value in [(src/'backend'/'app.db','main'), (tenant/'nested.session','tenant')]:
                db=sqlite3.connect(path); db.execute('create table t(v text)'); db.execute('insert into t values(?)',(value,)); db.commit(); db.close()
            (sessions/'.encryption.key').write_bytes(b'test-encryption-key')
            subprocess.run([PYTHON,str(ROOT/'scripts'/'backup_runtime.py'),'--project-root',str(src),'--output',str(archive)],check=True,stdout=subprocess.PIPE)
            subprocess.run([PYTHON,str(ROOT/'scripts'/'restore_runtime.py'),str(archive),'--project-root',str(dst),'--force'],check=True,stdout=subprocess.PIPE)
            db=sqlite3.connect(dst/'backend'/'sessions'/'user_test'/'nested.session')
            self.assertEqual(db.execute('select v from t').fetchone()[0], 'tenant'); db.close()
            self.assertEqual((dst/'backend'/'sessions'/'.encryption.key').read_bytes(), b'test-encryption-key')
            import json, tarfile
            with tarfile.open(archive,'r:gz') as tar:
                manifest=json.load(tar.extractfile('manifest.json'))
            self.assertTrue(manifest['encryption_key_included'])
            self.assertEqual(manifest['session_count'], 1)

    def test_include_env_does_not_claim_injected_secrets(self):
        with tempfile.TemporaryDirectory(prefix='mtm_backup_no_env_') as td:
            base = Path(td)
            src = base / 'src'
            archive = base / 'runtime.tar.gz'
            sessions = src / 'backend' / 'sessions'
            sessions.mkdir(parents=True)
            db_path = src / 'backend' / 'app.db'
            db = sqlite3.connect(db_path)
            db.execute('create table t(v text)')
            db.execute('insert into t values(?)', ('main-ok',))
            db.commit(); db.close()

            env = os.environ.copy()
            env.update({
                'DB_URL': f'sqlite+aiosqlite:///{db_path}',
                'DATABASE_URL': '',
                'SESSIONS_DIR': str(sessions),
                'SECRETS_ENCRYPTION_KEY': 'injected-secret-not-in-file',
            })
            proc = subprocess.run(
                [PYTHON, str(ROOT / 'scripts' / 'backup_runtime.py'), '--project-root', str(src), '--output', str(archive), '--include-env'],
                env=env, check=True, capture_output=True, text=True,
            )
            import json, tarfile
            result = json.loads(proc.stdout)
            self.assertFalse(result['includes_env'])
            self.assertIn('platform-injected secrets were NOT captured', proc.stderr)
            with tarfile.open(archive, 'r:gz') as tar:
                names = set(tar.getnames())
                self.assertIn('manifest.json', names)
                self.assertNotIn('backend.env', names)
                manifest = json.load(tar.extractfile('manifest.json'))
                self.assertFalse(manifest['includes_env'])



if __name__ == '__main__':
    unittest.main()
