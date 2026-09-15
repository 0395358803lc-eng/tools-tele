from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from pydantic import ValidationError
from app.auth import BootstrapIn
from app.routers.admin import AdminUserCreate, AdminUserUpdate
from app.supabase_identity import validate_password


class PasswordPolicyTests(unittest.TestCase):
    def test_strong_password_passes(self):
        validate_password('StrongPass12!')

    def test_short_password_fails(self):
        with self.assertRaises(ValueError):
            validate_password('Abc123!')

    def test_requires_upper_and_lower(self):
        for value in ('lowercase123!', 'UPPERCASE123!'):
            with self.assertRaises(ValueError):
                validate_password(value)

    def test_requires_digit_and_special(self):
        for value in ('StrongPassword!', 'StrongPassword12'):
            with self.assertRaises(ValueError):
                validate_password(value)

    def test_request_models_require_12_chars(self):
        with self.assertRaises(ValidationError):
            BootstrapIn(username='admin', password='Abc123!')
        with self.assertRaises(ValidationError):
            AdminUserCreate(username='user1', password='Abc123!')
        with self.assertRaises(ValidationError):
            AdminUserUpdate(password='Abc123!')

    def test_frontend_new_password_validation_present(self):
        admin = (ROOT / 'frontend' / 'src' / 'components' / 'AdminPage.jsx').read_text(encoding='utf-8')
        login = (ROOT / 'frontend' / 'src' / 'components' / 'LoginScreen.jsx').read_text(encoding='utf-8')
        self.assertIn('minLength={12}', admin)
        self.assertIn('minLength={bootstrap ? 12 : undefined}', login)
        self.assertIn('passwordError', admin)
        self.assertIn('passwordError', login)
        self.assertIn(r'!/\d/.test(value)', admin)
        self.assertIn(r'!/\d/.test(value)', login)
        self.assertNotIn(r'!/\\d/.test(value)', admin)
        self.assertNotIn(r'!/\\d/.test(value)', login)


if __name__ == '__main__':
    unittest.main()
