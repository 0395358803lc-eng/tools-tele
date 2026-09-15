from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import app.supabase_identity as identity


class IdentityProvisioningTests(unittest.TestCase):
    def fake_user(self, role=None):
        app_metadata = {} if role is None else {'role': role}
        return SimpleNamespace(
            id='test-user-id',
            email='probe@example.net',
            user_metadata={'username': 'probe'},
            app_metadata=app_metadata,
            banned_until=None,
            created_at=None,
            last_sign_in_at=None,
        )

    def test_missing_role_is_unprovisioned(self):
        out = identity.identity_from_user(self.fake_user())
        self.assertEqual(out.role, 'unprovisioned')
        self.assertFalse(out.is_admin)

    def _client_for(self, user):
        auth = SimpleNamespace(get_user=lambda _token: SimpleNamespace(user=user))
        return SimpleNamespace(auth=auth)

    def test_unprovisioned_access_token_is_rejected(self):
        from unittest.mock import patch
        with patch.object(identity, '_server_client', return_value=self._client_for(self.fake_user())):
            with self.assertRaises(PermissionError):
                identity.verify_access_token('test-token')

    def test_admin_and_user_access_tokens_are_allowed(self):
        from unittest.mock import patch
        for role in ('admin', 'user'):
            with patch.object(identity, '_server_client', return_value=self._client_for(self.fake_user(role))):
                out = identity.verify_access_token('test-token')
                self.assertEqual(out.role, role)

    def test_admin_summary_separates_unprovisioned(self):
        import asyncio
        from unittest.mock import patch
        import app.routers.admin as admin_router
        users = [
            identity.identity_from_user(self.fake_user('admin')),
            identity.identity_from_user(self.fake_user('user')),
            identity.identity_from_user(self.fake_user()),
        ]
        from unittest.mock import AsyncMock
        with patch.object(admin_router, 'list_users', return_value=users), \
             patch.object(admin_router, 'dashboard_counts', new=AsyncMock(return_value={})):
            summary = asyncio.run(admin_router.admin_summary(users[0]))
        self.assertEqual(summary['active_users'], 2)
        self.assertEqual(summary['unprovisioned_users'], 1)



if __name__ == '__main__':
    unittest.main()
