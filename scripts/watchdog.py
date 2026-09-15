#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOCK = ROOT / ".watchdog.lock"
MAINTENANCE = ROOT / ".maintenance"
TASK_BACKEND = "MTM_Backend"
TASK_NGROK = "MTM_Ngrok"
LOCAL_READY = "http://127.0.0.1:8000/api/health/ready"
PUBLIC_LIVE = "https://bony-issue-ramrod.ngrok-free.dev/api/health/live"


def set_ops_alert(code: str, active: bool, level: str, message: str) -> None:
    try:
        import sys
        backend = ROOT / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.ops_alerts import set_alert
        set_alert(code, active, level=level, message=message, source="watchdog")
    except Exception:
        pass


def logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("watchdog")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = RotatingFileHandler(LOG_DIR / "watchdog.log", maxBytes=2_000_000,
                                backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    return log


def acquire_lock() -> int | None:
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime > 600:
        LOCK.unlink(missing_ok=True)
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except FileExistsError:
        return None


def release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    finally:
        LOCK.unlink(missing_ok=True)


def probe(url: str, timeout: float = 5.0) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "MTM-Watchdog/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            if url.endswith("/ready"):
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("ok"))
            return True
    except Exception:
        return False


def task(action: str, name: str) -> None:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    cmd = [str(system32 / "schtasks.exe"), f"/{action}", "/TN", name]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def restart_task(name: str) -> None:
    task("End", name)
    time.sleep(1.5)
    task("Run", name)


def wait_probe(url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if probe(url):
            return True
        time.sleep(2)
    return probe(url)


def main() -> None:
    fd = acquire_lock()
    if fd is None:
        return
    log = logger()
    try:
        if MAINTENANCE.exists():
            log.info("maintenance_mode")
            return
        local_ok = probe(LOCAL_READY)
        if not local_ok:
            log.warning("backend_unhealthy restarting_task=%s", TASK_BACKEND)
            set_ops_alert("backend", True, "critical", "Backend readiness probe failed")
            restart_task(TASK_BACKEND)
            local_ok = wait_probe(LOCAL_READY, 40)
            log.info("backend_restart_result ok=%s", local_ok)
            if local_ok: set_ops_alert("backend", False, "info", "Backend recovered")

        public_ok = probe(PUBLIC_LIVE) if local_ok else False
        if local_ok and not public_ok:
            log.warning("public_tunnel_unhealthy restarting_task=%s", TASK_NGROK)
            set_ops_alert("ngrok", True, "critical", "Public tunnel probe failed")
            restart_task(TASK_NGROK)
            public_ok = wait_probe(PUBLIC_LIVE, 25)
            log.info("ngrok_restart_result ok=%s", public_ok)
            if public_ok: set_ops_alert("ngrok", False, "info", "Public tunnel recovered")

        if local_ok and public_ok:
            set_ops_alert("backend", False, "info", "Backend healthy")
            set_ops_alert("ngrok", False, "info", "Public tunnel healthy")
            log.info("watchdog_ok")
    finally:
        release_lock(fd)


if __name__ == "__main__":
    main()
