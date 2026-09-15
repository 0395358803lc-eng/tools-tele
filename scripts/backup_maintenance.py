#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def logger_for(root: Path) -> logging.Logger:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("backup_maintenance")
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = RotatingFileHandler(
            log_dir / "backup-maintenance.log", maxBytes=2_000_000,
            backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    return log


def prune(folder: Path, keep: int) -> int:
    files = sorted(folder.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in files[keep:]:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def run(root: Path) -> Path:
    now = datetime.now(timezone.utc)
    base = root / "backups" / "automated"
    daily = base / "daily"
    weekly = base / "weekly"
    monthly = base / "monthly"
    for folder in (daily, weekly, monthly):
        folder.mkdir(parents=True, exist_ok=True)

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    archive = daily / f"mtm-runtime-{stamp}.tar.gz"
    backup_script = root / "scripts" / "backup_runtime.py"
    restore_script = root / "scripts" / "restore_runtime.py"

    subprocess.run(
        [sys.executable, str(backup_script), "--project-root", str(root),
         "--output", str(archive)],
        cwd=root, check=True,
    )
    subprocess.run(
        [sys.executable, str(restore_script), str(archive),
         "--project-root", str(root), "--verify-only"],
        cwd=root, check=True,
    )
    iso = now.isocalendar()
    weekly_name = f"mtm-weekly-{iso.year}-W{iso.week:02d}.tar.gz"
    weekly_target = weekly / weekly_name
    if not weekly_target.exists():
        shutil.copy2(archive, weekly_target)

    monthly_name = f"mtm-monthly-{now.strftime('%Y-%m')}.tar.gz"
    monthly_target = monthly / monthly_name
    if not monthly_target.exists():
        shutil.copy2(archive, monthly_target)

    removed = {
        "daily": prune(daily, 7),
        "weekly": prune(weekly, 5),
        "monthly": prune(monthly, 3),
    }
    log = logger_for(root)
    log.info(
        "backup_ok archive=%s size=%d removed=%s",
        archive.name, archive.stat().st_size, removed,
    )
    try:
        backend = root / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.ops_alerts import set_alert
        set_alert("backup_failed", False, level="info", message="Backup recovered", source="backup")
    except Exception:
        pass
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    try:
        archive = run(root)
        print(f"BACKUP_OK={archive}")
    except Exception:
        logger_for(root).exception("backup_failed")
        try:
            backend = root / "backend"
            if str(backend) not in sys.path:
                sys.path.insert(0, str(backend))
            from app.ops_alerts import set_alert
            set_alert("backup_failed", True, level="critical", message="Scheduled backup failed", source="backup")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
