from __future__ import annotations

import unittest

from cryptography.fernet import Fernet

from backend.app.config import settings
from backend.app.models import AccountProxy
from backend.app.proxy_store import runtime_proxy_from_row, validate_proxy
from backend.app.secrets_store import encrypt_value


class ProxyStoreTests(unittest.TestCase):
    def test_validate_supported_proxy_types(self):
        self.assertEqual(validate_proxy('SOCKS5', '127.0.0.1', 1080), ('socks5', '127.0.0.1', 1080))
        self.assertEqual(validate_proxy('http', 'proxy.example', 8080), ('http', 'proxy.example', 8080))
        with self.assertRaises(ValueError):
            validate_proxy('ftp', '127.0.0.1', 21)
        with self.assertRaises(ValueError):
            validate_proxy('socks5', '', 1080)
        with self.assertRaises(ValueError):
            validate_proxy('socks5', '127.0.0.1', 70000)

    def test_runtime_proxy_decrypts_password_without_exposing_ciphertext(self):
        import tempfile
        previous = settings.SESSIONS_DIR
        td = tempfile.TemporaryDirectory(prefix='mtm_proxy_key_')
        try:
            settings.SESSIONS_DIR = td.name
            cipher = encrypt_value('secret-pass')
            self.assertNotIn('secret-pass', cipher)
            row = AccountProxy(
                account_id=1, enabled=True, proxy_type='socks5', host='10.0.0.2', port=1080,
                username='alice', password_ciphertext=cipher, rdns=True,
            )
            cfg = runtime_proxy_from_row(row)
            self.assertEqual(cfg['proxy_type'], 'socks5')
            self.assertEqual(cfg['addr'], '10.0.0.2')
            self.assertEqual(cfg['port'], 1080)
            self.assertEqual(cfg['username'], 'alice')
            self.assertEqual(cfg['password'], 'secret-pass')
            self.assertTrue(cfg['rdns'])
        finally:
            settings.SESSIONS_DIR = previous
            td.cleanup()

    def test_disabled_proxy_returns_none(self):
        row = AccountProxy(
            account_id=1, enabled=False, proxy_type='socks5', host='10.0.0.2', port=1080,
            rdns=True,
        )
        self.assertIsNone(runtime_proxy_from_row(row))


if __name__ == '__main__':
    unittest.main()
