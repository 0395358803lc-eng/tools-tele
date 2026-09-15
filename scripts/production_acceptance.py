#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import os
from dotenv import dotenv_values
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
for _key, _value in dotenv_values(BACKEND / '.env').items():
    if _value is not None:
        os.environ.setdefault(str(_key), str(_value))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import settings

LOCAL = 'http://127.0.0.1:8000'
PUBLIC = (settings.PUBLIC_URL or '').rstrip('/')


def probe(url: str) -> tuple[int, dict, dict]:
    req = Request(url, headers={'User-Agent': 'MTM-Acceptance/1.0'})
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            headers = {k.lower(): v for k, v in resp.headers.items()}
            try: body = json.loads(raw)
            except Exception: body = {}
            return int(resp.status), body, headers
    except HTTPError as exc:
        return int(exc.code), {}, {k.lower(): v for k, v in exc.headers.items()}


def check(condition: bool, name: str, failures: list[str]) -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}")
    if not condition:
        failures.append(name)


def task_exists(name: str) -> bool:
    system32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    result = subprocess.run([str(system32 / 'schtasks.exe'), '/Query', '/TN', name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def main() -> None:
    failures: list[str] = []
    status, ready, headers = probe(LOCAL + '/api/health/ready')
    check(status == 200 and ready.get('ok') is True, 'local_readiness', failures)
    check(ready.get('database_kind') == 'postgresql', 'postgresql_runtime', failures)
    check(ready.get('db_revision') == ready.get('expected_revision'), 'alembic_head', failures)
    check(bool(headers.get('x-request-id')), 'request_id_header', failures)

    if PUBLIC:
        status, _body, headers = probe(PUBLIC + '/api/health/live')
        check(status == 200, 'public_https', failures)
        check(bool(headers.get('strict-transport-security')), 'hsts', failures)
        check(headers.get('cache-control') == 'no-store', 'api_no_store', failures)
        status, _body, _headers = probe(PUBLIC + '/api/admin/health')
        check(status == 401, 'admin_requires_auth', failures)
    else:
        check(False, 'public_url_configured', failures)

    check(not (ROOT / '.maintenance').exists(), 'maintenance_off', failures)
    backup_root = ROOT / 'backups'
    backups = list(backup_root.rglob('*.tar.gz')) if backup_root.exists() else []
    check(bool(backups), 'backup_exists', failures)

    if failures:
        print('ACCEPTANCE=FAIL')
        print('FAILED=' + ','.join(failures))
        raise SystemExit(1)
    print('ACCEPTANCE=PASS')


if __name__ == '__main__':
    main()
