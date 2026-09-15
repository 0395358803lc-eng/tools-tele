#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import sys
from urllib.parse import parse_qs, unquote, urlsplit
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sqlite_snapshot(source: Path, dest: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        result = dst.execute('PRAGMA integrity_check').fetchone()
        if not result or str(result[0]).lower() != 'ok':
            raise RuntimeError(f'integrity_check failed for {source}')
    finally:
        dst.close()
        src.close()


def load_config(root: Path) -> dict[str, str]:
    values = {k: str(v or '') for k, v in dotenv_values(root / 'backend' / '.env').items()}
    for key in ('DB_URL', 'DATABASE_URL', 'SESSIONS_DIR'):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def sqlite_path(root: Path, url: str) -> Path:
    prefixes = ('sqlite+aiosqlite:///', 'sqlite:///')
    for prefix in prefixes:
        if url.startswith(prefix):
            raw = url[len(prefix):]
            p = Path(raw)
            return p if p.is_absolute() else (root / 'backend' / p).resolve()
    raise ValueError('DB_URL is not SQLite')


def postgres_url(raw: str) -> str:
    raw = raw.replace('postgresql+asyncpg://', 'postgresql://', 1)
    return raw.replace('?ssl=', '?sslmode=').replace('&ssl=', '&sslmode=')

def find_pg_tool(name: str) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found)
    exe = name + ('.exe' if os.name == 'nt' else '')
    candidates = [
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'pgAdmin 4' / 'runtime' / exe,
        Path(os.environ.get('ProgramFiles', '')) / 'pgAdmin 4' / 'runtime' / exe,
    ]
    base = Path(os.environ.get('ProgramFiles', '')) / 'PostgreSQL'
    if base.exists():
        candidates.extend(sorted(base.glob(f'*/bin/{exe}'), reverse=True))
    return next((item for item in candidates if item.is_file()), None)

def pg_connection(raw: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlsplit(postgres_url(raw))
    args: list[str] = []
    if parsed.hostname:
        args += ['--host', parsed.hostname]
    if parsed.port:
        args += ['--port', str(parsed.port)]
    if parsed.username:
        args += ['--username', unquote(parsed.username)]
    args += ['--dbname', parsed.path.lstrip('/') or 'postgres']
    env = os.environ.copy()
    if parsed.password:
        env['PGPASSWORD'] = unquote(parsed.password)
    sslmode = parse_qs(parsed.query).get('sslmode', [''])[0]
    if sslmode:
        env['PGSSLMODE'] = sslmode
    return args, env


def main() -> None:
    default_root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description='Tạo backup runtime Multi TG Manager có kiểm tra toàn vẹn')
    ap.add_argument('--project-root', type=Path, default=default_root)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--include-env', action='store_true', help='Bao gồm FILE backend/.env nếu có; secret do nền tảng inject sẽ không được lấy')
    args = ap.parse_args()

    root = args.project_root.resolve()
    backend = root / 'backend'
    cfg = load_config(root)
    db_url = (cfg.get('DATABASE_URL') or cfg.get('DB_URL') or 'sqlite+aiosqlite:///./app.db').strip()
    sessions_raw = cfg.get('SESSIONS_DIR') or './sessions'
    sessions_dir = Path(sessions_raw)
    if not sessions_dir.is_absolute():
        sessions_dir = (backend / sessions_dir).resolve()

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = args.output or (root / 'backups' / f'mtm-runtime-{stamp}.tar.gz')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='mtm_backup_') as td:
        stage = Path(td) / 'payload'
        stage.mkdir(parents=True)
        db_type = 'sqlite'

        if db_url.startswith(('postgres://', 'postgresql://', 'postgresql+asyncpg://')):
            db_type = 'postgresql'
            dump = stage / 'database.pgcustom'
            pg_dump = find_pg_tool('pg_dump')
            pg_restore = find_pg_tool('pg_restore')
            if not pg_dump or not pg_restore:
                raise SystemExit('Cần pg_dump và pg_restore để backup PostgreSQL')
            conn_args, pg_env = pg_connection(db_url)
            subprocess.run([str(pg_dump), '--format=custom', '--file', str(dump), *conn_args], env=pg_env, check=True)
            subprocess.run([str(pg_restore), '--list', str(dump)], stdout=subprocess.DEVNULL, check=True)
        else:
            sqlite_snapshot(sqlite_path(root, db_url), stage / 'database.sqlite')

        out_sessions = stage / 'sessions'
        out_sessions.mkdir()
        session_count = 0
        if sessions_dir.exists():
            for source in sorted(sessions_dir.rglob('*.session')):
                rel = source.relative_to(sessions_dir)
                sqlite_snapshot(source, out_sessions / rel)
                session_count += 1
            for name in ('twofa.enc', '.encryption.key'):
                for source in sorted(sessions_dir.rglob(name)):
                    rel = source.relative_to(sessions_dir)
                    dest = out_sessions / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)

        env_included = False
        if args.include_env:
            env_file = backend / '.env'
            if env_file.is_file():
                shutil.copy2(env_file, stage / 'backend.env')
                env_included = True
            else:
                print(
                    'CẢNH BÁO: đã yêu cầu --include-env nhưng backend/.env không tồn tại; '
                    'backend.env was not captured; platform-injected secrets were NOT captured; the internal encryption key is backed up with sessions when present.',
                    file=sys.stderr,
                )

        files = {}
        for file in sorted(p for p in stage.rglob('*') if p.is_file()):
            rel = file.relative_to(stage).as_posix()
            files[rel] = {'sha256': sha256(file), 'size': file.stat().st_size}
        manifest = {
            'format': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'database_type': db_type,
            'session_count': session_count,
            'includes_env': env_included,
            'encryption_key_included': any(k.endswith('.encryption.key') for k in files),
            'files': files,
        }
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')

        with tarfile.open(output, 'w:gz') as tar:
            for item in sorted(stage.iterdir()):
                tar.add(item, arcname=item.name, recursive=True)
        try:
            output.chmod(0o600)
        except OSError:
            pass

    print(json.dumps({'backup': str(output), 'database_type': db_type, 'sessions': session_count, 'includes_env': env_included}, indent=2))


if __name__ == '__main__':
    main()
