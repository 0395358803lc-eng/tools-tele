import asyncio
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def load_checker():
    spec = importlib.util.spec_from_file_location('mtm_production_check', ROOT / 'scripts' / 'production_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductionCheckSecretStoreTests(unittest.TestCase):
    def test_encrypted_sql_telegram_api_is_accepted(self):
        checker = load_checker()
        with tempfile.TemporaryDirectory(prefix='mtm_prodcheck_') as td:
            db_path = Path(td) / 'app.db'
            key = Fernet.generate_key()
            cipher = Fernet(key)
            conn = sqlite3.connect(db_path)
            conn.execute('create table encrypted_secrets (key text primary key, ciphertext text not null)')
            conn.executemany(
                'insert into encrypted_secrets(key,ciphertext) values (?,?)',
                [
                    ('telegram:api_id', cipher.encrypt(b'123456').decode()),
                    ('telegram:api_hash', cipher.encrypt(b'abc123hash').decode()),
                ],
            )
            conn.commit(); conn.close()
            url = f'sqlite+aiosqlite:///{db_path}'
            self.assertTrue(asyncio.run(checker.database_has_telegram_api(url, key.decode())))
            self.assertFalse(asyncio.run(checker.database_has_telegram_api(url, Fernet.generate_key().decode())))

    def test_relative_sqlite_url_is_resolved_from_backend(self):
        checker = load_checker()
        normalized = checker.normalize_async_url('sqlite+aiosqlite:///./app.db')
        self.assertEqual(normalized, 'sqlite+aiosqlite:///' + str((ROOT / 'backend' / 'app.db').resolve()))


if __name__ == '__main__':
    unittest.main()
