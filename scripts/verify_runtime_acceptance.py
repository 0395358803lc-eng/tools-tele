#!/usr/bin/env python3
from __future__ import annotations

import http.cookiejar
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def request(opener, method: str, url: str, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req_headers = {'Accept': 'application/json'}
    if data is not None:
        req_headers['Content-Type'] = 'application/json'
    req_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        resp = opener.open(req, timeout=5)
        raw = resp.read()
        return resp.status, resp.headers, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw.decode('utf-8', 'replace')
        return exc.code, exc.headers, parsed


def wait_live(url: str, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('runtime server did not become live')


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='mtm_runtime_accept_') as td:
        temp = Path(td)
        db_path = temp / 'runtime.db'
        sessions = temp / 'sessions'
        sessions.mkdir()
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        env = os.environ.copy()
        env.update({
            'DB_URL': f'sqlite+aiosqlite:///{db_path}',
            'DATABASE_URL': '',
            'SESSIONS_DIR': str(sessions),
            'APP_PASSWORD': 'runtime-acceptance-password',
            'TG_API_ID': '12345',
            'TG_API_HASH': '0123456789abcdef0123456789abcdef',
            'SECRETS_ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'COOKIE_SECURE': 'false',
            'TRUST_PROXY_HEADERS': 'false',
            'NODE_ENV': 'development',
            'RATE_MIN': '0',
            'RATE_MAX': '0',
        })
        subprocess.run(
            [PYTHON, '-m', 'alembic', 'upgrade', 'head'],
            cwd=BACKEND, env=env, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc = subprocess.Popen(
            [PYTHON, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--workers', '1'],
            cwd=BACKEND, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            wait_live(base + '/api/health/live')
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

            status, _, ready = request(opener, 'GET', base + '/api/health/ready')
            assert status == 200 and ready['ok'] is True

            status, _, protected = request(opener, 'GET', base + '/api/system/status')
            assert status == 401

            status, headers, login = request(
                opener, 'POST', base + '/api/auth-app/login',
                {'password': 'runtime-acceptance-password'},
            )
            assert status == 200 and login['ok'] is True
            set_cookie = headers.get('Set-Cookie', '')
            lower_cookie = set_cookie.lower()
            assert 'httponly' in lower_cookie
            assert 'samesite=strict' in lower_cookie
            assert any(c.name == 'mtm_session' for c in jar)

            status, _, system = request(opener, 'GET', base + '/api/system/status')
            assert status == 200 and system['db_revision'] == system['expected_revision']

            metrics_req = urllib.request.Request(base + '/api/system/metrics', method='GET')
            with opener.open(metrics_req, timeout=5) as resp:
                metrics = resp.read().decode('utf-8')
                assert resp.status == 200
                assert 'mtm_accounts_total ' in metrics
                assert 'password' not in metrics.lower()

            status, _, blocked = request(
                opener, 'POST', base + '/api/auth-app/logout', None,
                {'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'},
            )
            assert status == 403 and blocked['detail'] == 'Cross-site request blocked'

            status, _, me = request(opener, 'GET', base + '/api/auth-app/me')
            assert status == 200 and me['authed'] is True

            status, _, logout = request(
                opener, 'POST', base + '/api/auth-app/logout', None,
                {'Origin': base, 'Sec-Fetch-Site': 'same-origin'},
            )
            assert status == 200 and logout['ok'] is True
            status, _, me = request(opener, 'GET', base + '/api/auth-app/me')
            assert status == 200 and me['authed'] is False

            # A fresh client from the same IP should be limited after five failures.
            no_cookie = urllib.request.build_opener()
            failure_codes = []
            for _ in range(6):
                code, _, _ = request(no_cookie, 'POST', base + '/api/auth-app/login', {'password': 'wrong-password'})
                failure_codes.append(code)
            assert failure_codes[:5] == [401] * 5
            assert failure_codes[5] == 429

            print(json.dumps({
                'ready': True,
                'protected_unauthenticated': True,
                'login_cookie': True,
                'csrf_cross_site_blocked': True,
                'logout_revoked': True,
                'login_rate_limit': True,
                'metrics_authenticated': True,
            }, sort_keys=True))
            print('RUNTIME_ACCEPTANCE_OK')
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
            try:
                output, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                output, _ = proc.communicate(timeout=5)
                raise RuntimeError('runtime server did not shut down after SIGTERM')
            if proc.returncode not in (0, -signal.SIGTERM):
                raise RuntimeError(f'runtime server exited with {proc.returncode}\n{output[-4000:]}')
            if 'Application shutdown complete' not in output:
                raise RuntimeError('runtime server did not report clean application shutdown')


if __name__ == '__main__':
    main()
