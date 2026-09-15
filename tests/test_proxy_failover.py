from __future__ import annotations

import tempfile
import unittest
from cryptography.fernet import Fernet

from backend.app.config import settings
from backend.app.models import AccountProxy
from backend.app.proxy_store import runtime_proxy_from_row, has_fallback
from backend.app.secrets_store import encrypt_value


class ProxyFailoverTests(unittest.TestCase):
    def test_primary_and_fallback_are_isolated(self):
        previous = settings.SESSIONS_DIR
        td = tempfile.TemporaryDirectory(prefix="mtm_proxy_failover_")
        try:
            settings.SESSIONS_DIR = td.name
            row = AccountProxy(
                account_id=1, enabled=True, proxy_type="socks5", host="10.0.0.1", port=1080,
                username="primary", password_ciphertext=encrypt_value("primary-secret"), rdns=True,
                fallback_enabled=True, fallback_proxy_type="http", fallback_host="10.0.0.2", fallback_port=8080,
                fallback_username="backup", fallback_password_ciphertext=encrypt_value("backup-secret"),
                fallback_rdns=False, active_slot="primary", failover_count=0,
            )
            self.assertTrue(has_fallback(row))
            primary = runtime_proxy_from_row(row)
            self.assertEqual(primary["addr"], "10.0.0.1")
            self.assertEqual(primary["password"], "primary-secret")
            self.assertNotEqual(row.password_ciphertext, "primary-secret")
            row.active_slot = "fallback"
            fallback = runtime_proxy_from_row(row)
            self.assertEqual(fallback["addr"], "10.0.0.2")
            self.assertEqual(fallback["proxy_type"], "http")
            self.assertEqual(fallback["password"], "backup-secret")
            self.assertFalse(fallback["rdns"])
            self.assertNotEqual(row.fallback_password_ciphertext, "backup-secret")
        finally:
            settings.SESSIONS_DIR = previous
            td.cleanup()

    def test_missing_fallback_does_not_activate(self):
        row = AccountProxy(
            account_id=2, enabled=True, proxy_type="socks5", host="10.0.0.1", port=1080,
            rdns=True, fallback_enabled=False, active_slot="fallback",
        )
        self.assertFalse(has_fallback(row))
        cfg = runtime_proxy_from_row(row)
        self.assertEqual(cfg["slot"], "primary")


if __name__ == "__main__":
    unittest.main()
