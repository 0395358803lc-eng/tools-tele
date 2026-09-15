from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .config import settings

ROOT = Path(__file__).resolve().parents[2]
STATIC_INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def _git_sha_from_metadata(root: Path) -> str:
    marker = root / ".git"
    git_dir = marker
    if marker.is_file():
        line = marker.read_text(encoding="utf-8", errors="replace").strip()
        if not line.lower().startswith("gitdir:"):
            return ""
        git_dir = Path(line.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (marker.parent / git_dir).resolve()
    if not git_dir.is_dir():
        return ""
    head = (git_dir / "HEAD")
    if not head.is_file():
        return ""
    value = head.read_text(encoding="ascii", errors="replace").strip()
    if value.startswith("ref:"):
        ref = value.split(":", 1)[1].strip()
        ref_file = git_dir / ref
        if ref_file.is_file():
            value = ref_file.read_text(encoding="ascii", errors="replace").strip()
        else:
            packed = git_dir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="ascii", errors="replace").splitlines():
                    if line.startswith("#") or line.startswith("^"):
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) == 2 and parts[1].strip() == ref:
                        value = parts[0].strip()
                        break
                else:
                    return ""
            else:
                return ""
    if len(value) >= 12 and all(c in "0123456789abcdefABCDEF" for c in value):
        return value[:12]
    return ""


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
            sha = _git_sha_from_metadata(ROOT)
    if not sha:
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
