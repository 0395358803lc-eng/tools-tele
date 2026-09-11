from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi import Request
from sqlalchemy import BigInteger
from starlette.responses import JSONResponse

from app.audit import _sanitize
from app.config import settings
from app.models import Account, GoneAccount, SecurityMessage
from app.schemas import BulkDeleteMyMessagesIn, BulkLeaveAllIn, BulkWipeChatIn
from app.security_middleware import BrowserSecurityMiddleware
from app.utils import friendly_error
from app.telegram_errors import classify_error


class CoreTests(unittest.TestCase):
    def test_audit_redacts_sensitive_fields(self):
        out = _sanitize({
            'password': 'p', 'otp_code': '12345', 'message_text': 'hello',
            'token': 'abc', 'target': '@safe', 'count': 2,
        })
        self.assertEqual(out['password'], '[redacted]')
        self.assertEqual(out['otp_code'], '[redacted]')
        self.assertEqual(out['message_text'], '[redacted]')
        self.assertEqual(out['token'], '[redacted]')
        self.assertEqual(out['target'], '@safe')
        self.assertEqual(out['count'], 2)

    def test_telegram_ids_are_bigint(self):
        self.assertIsInstance(Account.__table__.c.tg_user_id.type, BigInteger)
        self.assertIsInstance(GoneAccount.__table__.c.tg_user_id.type, BigInteger)
        self.assertIsInstance(SecurityMessage.__table__.c.tg_msg_id.type, BigInteger)

    def test_destructive_models_require_explicit_confirmation(self):
        self.assertFalse(BulkLeaveAllIn(account_ids=[1]).confirm)
        self.assertFalse(BulkDeleteMyMessagesIn(account_ids=[1]).confirm)
        self.assertFalse(BulkWipeChatIn(account_ids=[1], target='@x').confirm)
        self.assertTrue(BulkLeaveAllIn(account_ids=[1], confirm=True).confirm)

    def test_production_cors_does_not_include_dev_origin(self):
        main_source = (ROOT / 'backend' / 'app' / 'main.py').read_text(encoding='utf-8')
        config_source = (ROOT / 'backend' / 'app' / 'config.py').read_text(encoding='utf-8')
        checker = (ROOT / 'scripts' / 'production_check.py').read_text(encoding='utf-8')
        self.assertIn('NODE_ENV', main_source)
        self.assertIn('cors_origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])', main_source)
        self.assertIn('!= "production"', main_source)
        self.assertIn('ALLOWED_ORIGIN: str = ""', config_source)
        self.assertIn('Không được dùng ALLOWED_ORIGIN chỉ dành cho dev trong production', checker)

    def test_production_check_reads_allowed_origin_from_environment(self):
        checker = (ROOT / 'scripts' / 'production_check.py').read_text(encoding='utf-8')
        self.assertIn("'ALLOWED_ORIGIN'", checker)
        self.assertIn("--check-db", checker)
        self.assertIn("Kết nối PostgreSQL thành công tại Alembic head", checker)

    def test_strict_production_check_requires_secure_cookie(self):
        checker = (ROOT / 'scripts' / 'production_check.py').read_text(encoding='utf-8')
        self.assertIn("Production HTTPS yêu cầu COOKIE_SECURE=true", checker)
        self.assertIn("elif args.strict", checker)

    def test_strict_production_check_requires_single_instance_guard(self):
        checker = (ROOT / 'scripts' / 'production_check.py').read_text(encoding='utf-8')
        self.assertIn("Telegram production yêu cầu ENFORCE_SINGLE_INSTANCE=true", checker)
        self.assertIn("Đã bật cơ chế PostgreSQL bảo vệ chế độ một instance", checker)

    def test_strict_production_check_blocks_autoscale(self):
        checker = (ROOT / 'scripts' / 'production_check.py').read_text(encoding='utf-8')
        self.assertIn("Deployment hiện là autoscale", checker)
        self.assertIn("if args.strict: blockers.append(msg)", checker)

    def test_production_launcher_has_preflight_and_single_worker(self):
        launcher = (ROOT / 'run-production.sh').read_text(encoding='utf-8')
        self.assertIn('production_check.py" --strict', launcher)
        self.assertIn('production_check.py" --strict --check-db', launcher)
        self.assertIn('--workers 1', launcher)
        first = launcher.index('production_check.py" --strict')
        migration = launcher.index('alembic upgrade head')
        db_probe = launcher.index('production_check.py" --strict --check-db')
        self.assertLess(first, migration)
        self.assertLess(migration, db_probe)

    def test_no_raw_exception_details_in_http_400(self):
        router_dir = ROOT / 'backend' / 'app' / 'routers'
        forbidden = ('HTTPException(400, str(e))', 'HTTPException(400, f"')
        offenders = []
        for path in router_dir.glob('*.py'):
            text = path.read_text(encoding='utf-8')
            if forbidden[0] in text:
                offenders.append(path.name + ':str(e)')
            for line in text.splitlines():
                if 'HTTPException(400' in line and '{e}' in line:
                    offenders.append(path.name + ':raw-fstring')
        self.assertEqual(offenders, [])

    def test_generic_friendly_error_does_not_echo_exception_text(self):
        msg = friendly_error(ValueError("password=super-secret internal/path"))
        self.assertIn("ValueError", msg)
        self.assertNotIn("super-secret", msg)
        self.assertNotIn("internal/path", msg)

    def test_network_error_classification(self):
        info = classify_error(TimeoutError('timeout'))
        self.assertEqual(info.category, 'network')
        self.assertEqual(info.status, 'network_error')
        self.assertTrue(info.retryable)


class BrowserSecurityTests(unittest.IsolatedAsyncioTestCase):
    def make_request(self, method='POST', origin=None, fetch_site=None, cookie=True):
        headers = [(b'host', b'testserver')]
        if cookie:
            headers.append((b'cookie', b'mtm_session=dummy'))
        if origin:
            headers.append((b'origin', origin.encode()))
        if fetch_site:
            headers.append((b'sec-fetch-site', fetch_site.encode()))
        scope = {
            'type': 'http', 'http_version': '1.1', 'method': method,
            'scheme': 'http', 'path': '/write', 'raw_path': b'/write',
            'query_string': b'', 'headers': headers,
            'client': ('127.0.0.1', 12345), 'server': ('testserver', 80),
            'root_path': '',
        }
        return Request(scope)

    async def test_same_origin_allowed_cross_site_blocked(self):
        middleware = BrowserSecurityMiddleware(app=lambda scope, receive, send: None)

        async def next_ok(_request):
            return JSONResponse({'ok': True})

        same = await middleware.dispatch(
            self.make_request(origin='http://testserver', fetch_site='same-origin'), next_ok
        )
        cross = await middleware.dispatch(
            self.make_request(origin='https://evil.example', fetch_site='cross-site'), next_ok
        )
        bad_origin = await middleware.dispatch(
            self.make_request(origin='https://evil.example'), next_ok
        )
        cli = await middleware.dispatch(self.make_request(), next_ok)

        self.assertEqual(same.status_code, 200)
        self.assertEqual(cross.status_code, 403)
        self.assertEqual(bad_origin.status_code, 403)
        self.assertEqual(cli.status_code, 200)

    async def test_api_request_timeout_returns_504(self):
        middleware = BrowserSecurityMiddleware(app=lambda scope, receive, send: None)

        async def slow(_request):
            await asyncio.sleep(0.3)
            return JSONResponse({'ok': True})

        previous = settings.API_REQUEST_TIMEOUT_SECONDS
        settings.API_REQUEST_TIMEOUT_SECONDS = 0.1
        try:
            response = await middleware.dispatch(self.make_request(method='GET', cookie=False), slow)
        finally:
            settings.API_REQUEST_TIMEOUT_SECONDS = previous
        self.assertEqual(response.status_code, 504)
        self.assertTrue(response.headers.get('x-request-id'))
        self.assertEqual(response.headers['x-frame-options'], 'DENY')

    async def test_security_headers_added(self):
        middleware = BrowserSecurityMiddleware(app=lambda scope, receive, send: None)

        async def next_ok(_request):
            return JSONResponse({'ok': True})

        response = await middleware.dispatch(self.make_request(method='GET', cookie=False), next_ok)
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertIn('frame-ancestors', response.headers['content-security-policy'])
        self.assertTrue(response.headers.get('x-request-id'))


if __name__ == '__main__':
    unittest.main()
