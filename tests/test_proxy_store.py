from __future__ import annotations

import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from backend.app.config import settings
from backend.app.models import AccountProxy
from backend.app.proxy_store import runtime_proxy_from_row, validate_proxy
from backend.app.secrets_store import encrypt_value
from backend.app.routers.proxies import ProxyDraftTestIn, _draft_proxy_config

ROOT = Path(__file__).resolve().parents[1]


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


    def test_presave_draft_reuses_or_clears_saved_passwords(self):
        import tempfile
        previous = settings.SESSIONS_DIR
        td = tempfile.TemporaryDirectory(prefix='mtm_proxy_draft_key_')
        try:
            settings.SESSIONS_DIR = td.name
            row = AccountProxy(
                account_id=1, enabled=True, proxy_type='socks5', host='old-primary', port=1080,
                username='alice', password_ciphertext=encrypt_value('saved-primary'), rdns=True,
                fallback_enabled=True, fallback_proxy_type='http', fallback_host='old-fallback', fallback_port=8080,
                fallback_username='bob', fallback_password_ciphertext=encrypt_value('saved-fallback'), fallback_rdns=False,
                active_slot='primary',
            )
            primary = ProxyDraftTestIn(host='new-primary', port=1081, username='alice', password=None, slot='primary')
            slot, cfg = _draft_proxy_config(row, primary)
            self.assertEqual(slot, 'primary')
            self.assertEqual(cfg['addr'], 'new-primary')
            self.assertEqual(cfg['password'], 'saved-primary')

            cleared = ProxyDraftTestIn(host='new-primary', port=1081, username='alice', clear_password=True, slot='primary')
            _, cfg = _draft_proxy_config(row, cleared)
            self.assertIsNone(cfg['password'])

            fallback = ProxyDraftTestIn(
                host='new-primary', port=1081, fallback_enabled=True, fallback_proxy_type='http',
                fallback_host='new-fallback', fallback_port=8081, fallback_username='bob', slot='fallback',
            )
            slot, cfg = _draft_proxy_config(row, fallback)
            self.assertEqual(slot, 'fallback')
            self.assertEqual(cfg['addr'], 'new-fallback')
            self.assertEqual(cfg['password'], 'saved-fallback')
        finally:
            settings.SESSIONS_DIR = previous
            td.cleanup()

    def test_proxy_ui_exposes_presave_test(self):
        api = (ROOT / 'frontend' / 'src' / 'lib' / 'api.js').read_text(encoding='utf-8')
        ui = (ROOT / 'frontend' / 'src' / 'tabs' / 'ProxyTab.jsx').read_text(encoding='utf-8')
        self.assertIn('testProxyConfig', api)
        self.assertIn('/test-config', api)
        self.assertIn("testDraft('primary')", ui)
        self.assertIn("testDraft('fallback')", ui)
        self.assertIn('Test biểu mẫu chính', ui)

    def test_disabled_proxy_returns_none(self):
        row = AccountProxy(
            account_id=1, enabled=False, proxy_type='socks5', host='10.0.0.2', port=1080,
            rdns=True,
        )
        self.assertIsNone(runtime_proxy_from_row(row))


if __name__ == '__main__':
    unittest.main()
