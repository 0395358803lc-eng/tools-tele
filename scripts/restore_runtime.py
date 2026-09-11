#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in tar.getmembers():
        resolved = (target / member.name).resolve()
        if root not in resolved.parents and resolved != root:
            raise RuntimeError(f'Unsafe archive member: {member.name}')
        if member.issym() or member.islnk():
            raise RuntimeError(f'Links are not allowed in backup archives: {member.name}')
    tar.extractall(target, filter="data")


def verify(stage: Path) -> dict:
    manifest_path = stage / 'manifest.json'
    if not manifest_path.is_file():
        raise RuntimeError('manifest.json missing')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != 1:
        raise RuntimeError('Unsupported backup format')
    for rel, expected in manifest.get('files', {}).items():
        file = stage / rel
        if not file.is_file():
            raise RuntimeError(f'Backup file missing: {rel}')
        if file.stat().st_size != expected['size'] or sha256(file) != expected['sha256']:
            raise RuntimeError(f'Checksum mismatch: {rel}')
    return manifest


def main() -> None:
    default_root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description='Xác minh và phục hồi backup runtime Multi TG Manager')
    ap.add_argument('archive', type=Path)
    ap.add_argument('--project-root', type=Path, default=default_root)
    ap.add_argument('--force', action='store_true', help='Bắt buộc trước khi thay thế dữ liệu runtime hiện có')
    ap.add_argument('--restore-env', action='store_true')
    ap.add_argument('--postgres-url', default='', help='URL PostgreSQL đích khi phục hồi PostgreSQL dump')
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args()

    archive = args.archive.resolve()
    root = args.project_root.resolve()
    backend = root / 'backend'
    with tempfile.TemporaryDirectory(prefix='mtm_restore_') as td:
        stage = Path(td) / 'payload'
        stage.mkdir(parents=True)
        with tarfile.open(archive, 'r:gz') as tar:
            safe_extract(tar, stage)
        manifest = verify(stage)
        print(f"đã xác minh {len(manifest.get('files', {}))} tệp; cơ_sở_dữ_liệu={manifest.get('database_type')}")
        if args.verify_only:
            return
        if not args.force:
            raise SystemExit('Từ chối phục hồi khi chưa có --force. Hãy dừng ứng dụng rồi chạy lại với --force.')

        backend.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        db_type = manifest.get('database_type')
        if db_type == 'sqlite':
            src = stage / 'database.sqlite'
            dest = backend / 'app.db'
            if dest.exists():
                shutil.copy2(dest, backend / f'app.db.pre-restore-{stamp}.bak')
            shutil.copy2(src, dest)
        elif db_type == 'postgresql':
            if not args.postgres_url:
                raise SystemExit('Cần --postgres-url để phục hồi PostgreSQL')
            if not shutil.which('pg_restore'):
                raise SystemExit('Cần pg_restore để phục hồi PostgreSQL')
            subprocess.run(['pg_restore', '--clean', '--if-exists', '--no-owner', '--dbname', args.postgres_url, str(stage / 'database.pgcustom')], check=True)
        else:
            raise RuntimeError(f'Unknown database type: {db_type}')

        src_sessions = stage / 'sessions'
        dest_sessions = backend / 'sessions'
        if dest_sessions.exists():
            backup_sessions = backend / f'sessions.pre-restore-{stamp}'
            if backup_sessions.exists():
                shutil.rmtree(backup_sessions)
            shutil.move(str(dest_sessions), str(backup_sessions))
        shutil.copytree(src_sessions, dest_sessions)

        env_src = stage / 'backend.env'
        if args.restore_env:
            if not env_src.is_file():
                raise SystemExit('Backup không chứa backend.env')
            env_dest = backend / '.env'
            if env_dest.exists():
                shutil.copy2(env_dest, backend / f'.env.pre-restore-{stamp}.bak')
            shutil.copy2(env_src, env_dest)

    print('restore_complete')


if __name__ == '__main__':
    main()
