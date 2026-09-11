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
    return raw.replace('postgresql+asyncpg://', 'postgresql://', 1)


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
            if not shutil.which('pg_dump'):
                raise SystemExit('Cần pg_dump để backup PostgreSQL')
            subprocess.run(['pg_dump', '--format=custom', '--file', str(dump), postgres_url(db_url)], check=True)
        else:
            sqlite_snapshot(sqlite_path(root, db_url), stage / 'database.sqlite')

        out_sessions = stage / 'sessions'
        out_sessions.mkdir()
        session_count = 0
        if sessions_dir.exists():
            for source in sorted(sessions_dir.glob('*.session')):
                sqlite_snapshot(source, out_sessions / source.name)
                session_count += 1
            for name in ('twofa.enc',):
                source = sessions_dir / name
                if source.is_file():
                    shutil.copy2(source, out_sessions / name)

        env_included = False
        if args.include_env:
            env_file = backend / '.env'
            if env_file.is_file():
                shutil.copy2(env_file, stage / 'backend.env')
                env_included = True
            else:
                print(
                    'CẢNH BÁO: đã yêu cầu --include-env nhưng backend/.env không tồn tại; '
                    'platform-injected secrets were NOT captured. Back up SECRETS_ENCRYPTION_KEY separately.',
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
