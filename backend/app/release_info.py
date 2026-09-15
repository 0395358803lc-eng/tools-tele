from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .config import settings

ROOT = Path(__file__).resolve().parents[2]
STATIC_INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


@lru_cache(maxsize=1)
def release_info() -> dict[str, str]:
    sha = (settings.BUILD_SHA or "").strip()
    if not sha:
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT,
                text=True, stderr=subprocess.DEVNULL, timeout=2,
            ).strip()
        except Exception:
            sha = "unversioned"
    built = (settings.BUILD_TIMESTAMP or "").strip()
    if not built and STATIC_INDEX.is_file():
        built = datetime.fromtimestamp(
            STATIC_INDEX.stat().st_mtime, timezone.utc
        ).isoformat()
    if not built:
        built = datetime.now(timezone.utc).isoformat()
    return {
        "version": (settings.APP_VERSION or "1.0.0").strip() or "1.0.0",
        "git_sha": sha,
        "build_timestamp": built,
        "environment": (settings.NODE_ENV or "development").strip().lower(),
    }
