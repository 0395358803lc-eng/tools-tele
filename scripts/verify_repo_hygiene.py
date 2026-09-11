#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]

FORBIDDEN_TRACKED = [
    re.compile(r'(^|/)\.env$'),
    re.compile(r'(^|/)app\.db(?:$|\.)'),
    re.compile(r'\.session(?:$|\.)'),
    re.compile(r'(^|/)twofa\.(?:json|enc)$'),
    re.compile(r'(^|/)backups?/'),
    re.compile(r'\.pre-restore-.*\.bak$'),
]

SECRET_PATTERNS = {
    'openai_api_key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'telegram_hash_assignment': re.compile(r'(?i)\bTG_API_HASH\s*=\s*[0-9a-f]{32}\b'),
    'fernet_key_assignment': re.compile(r'\bSECRETS_ENCRYPTION_KEY\s*=\s*[A-Za-z0-9_-]{43}='),
}


def tracked_files() -> list[str]:
    out = subprocess.check_output(['git', 'ls-files'], cwd=WORKSPACE, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def skip_content_scan(rel: str) -> bool:
    normalized = rel.replace('\\', '/')
    return (
        '/tests/' in normalized
        or normalized.endswith('.env.example')
        or normalized.endswith('README.md')
        or normalized.endswith('TECHNICAL_ACCEPTANCE.md')
        or '/scripts/verify_runtime_acceptance.py' in normalized
        or '/scripts/verify_postgres_integration.sh' in normalized
    )


def main() -> None:
    files = tracked_files()
    bad_paths = []
    secret_hits = []
    for rel in files:
        if any(pattern.search(rel) for pattern in FORBIDDEN_TRACKED):
            bad_paths.append(rel)
        if skip_content_scan(rel):
            continue
        path = WORKSPACE / rel
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                secret_hits.append((rel, name))

    if bad_paths or secret_hits:
        for rel in bad_paths:
            print(f'FORBIDDEN_TRACKED_FILE {rel}')
        for rel, kind in secret_hits:
            print(f'POSSIBLE_SECRET {kind} {rel}')
        raise SystemExit(1)
    print(f'REPO_HYGIENE_OK tracked_files={len(files)}')


if __name__ == '__main__':
    main()
