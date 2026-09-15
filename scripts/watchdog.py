#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOCK = ROOT / ".watchdog.lock"
STATE = LOG_DIR / "watchdog-state.json"
MAINTENANCE = ROOT / ".maintenance"
TASK_BACKEND = "MTM_Backend"
TASK_NGROK = "MTM_Ngrok"
LOCAL_LIVE = "http://127.0.0.1:8000/api/health/live"
LOCAL_READY = "http://127.0.0.1:8000/api/health/ready"
PUBLIC_LIVE = "https://bony-issue-ramrod.ngrok-free.dev/api/health/live"
RESTART_WINDOW_SECONDS = 15 * 60
RESTART_LIMIT = 3


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
        handler = RotatingFileHandler(
            LOG_DIR / "watchdog.log", maxBytes=2_000_000,
            backupCount=3, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
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


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"restarts": {}}


def save_state(state: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STATE)


def permit_restart(name: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    state = load_state()
    restarts = state.setdefault("restarts", {})
    history = [
        float(ts) for ts in restarts.get(name, [])
        if now - float(ts) < RESTART_WINDOW_SECONDS
    ]
    if len(history) >= RESTART_LIMIT:
        restarts[name] = history
        save_state(state)
        return False
    history.append(now)
    restarts[name] = history
    save_state(state)
    return True


def probe(url: str, timeout: float = 5.0) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "MTM-Watchdog/1.1"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def readiness(timeout: float = 5.0) -> tuple[bool, dict, str]:
    req = Request(LOCAL_READY, headers={"User-Agent": "MTM-Watchdog/1.1"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok")), data, "ok"
    except HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            data = {}
        return False, data, f"http_{exc.code}"
    except Exception as exc:
        return False, {}, type(exc).__name__


def readiness_category(data: dict) -> str:
    failed = [str(x).lower() for x in data.get("failed_checks", [])]
    if any("database" in x or "postgres" in x or "alembic" in x for x in failed):
        return "database"
    return "backend"


def internet_available(timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            return True
    except OSError:
        return False


def task(action: str, name: str) -> None:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    cmd = [str(system32 / "schtasks.exe"), f"/{action}", "/TN", name]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def restart_task(name: str, log: logging.Logger) -> bool:
    if not permit_restart(name):
        log.error("restart_suppressed task=%s limit=%s window_seconds=%s", name, RESTART_LIMIT, RESTART_WINDOW_SECONDS)
        set_ops_alert(
            f"{name.lower()}_restart_suppressed", True, "critical",
            f"Restart circuit breaker opened for {name}",
        )
        return False
    task("End", name)
    time.sleep(1.5)
    task("Run", name)
    set_ops_alert(f"{name.lower()}_restart_suppressed", False, "info", "Restart circuit breaker closed")
    return True


def wait_probe(url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if probe(url):
            return True
        time.sleep(2)
    return probe(url)


def handle_backend(log: logging.Logger) -> bool:
    live_ok = probe(LOCAL_LIVE)
    ready_ok, ready_data, ready_reason = readiness()
    if live_ok and ready_ok:
        set_ops_alert("backend", False, "info", "Backend healthy")
        set_ops_alert("database", False, "info", "Database healthy")
        return True
    category = readiness_category(ready_data) if live_ok else "backend"
    if live_ok and category == "database":
        failed = ready_data.get("failed_checks", [])
        log.error("database_unhealthy failed_checks=%s reason=%s", failed, ready_reason)
        set_ops_alert("database", True, "critical", "Database/readiness check failed")
        return False

    log.warning(
        "backend_unhealthy live_ok=%s ready_ok=%s reason=%s restarting_task=%s",
        live_ok, ready_ok, ready_reason, TASK_BACKEND,
    )
    set_ops_alert("backend", True, "critical", "Backend health probe failed")
    if not restart_task(TASK_BACKEND, log):
        return False
    recovered = wait_probe(LOCAL_READY, 45)
    log.info("backend_restart_result ok=%s", recovered)
    if recovered:
        set_ops_alert("backend", False, "info", "Backend recovered")
        set_ops_alert("database", False, "info", "Database healthy")
    return recovered


def handle_public(log: logging.Logger) -> bool:
    if probe(PUBLIC_LIVE):
        set_ops_alert("ngrok", False, "info", "Public tunnel healthy")
        set_ops_alert("network", False, "info", "Network healthy")
        return True
    if not internet_available():
        log.error("network_unavailable public_probe_failed=true")
        set_ops_alert("network", True, "critical", "Outbound network unavailable")
        return False

    set_ops_alert("network", False, "info", "Network healthy")
    log.warning("public_tunnel_unhealthy restarting_task=%s", TASK_NGROK)
    set_ops_alert("ngrok", True, "critical", "Public tunnel probe failed")
    if not restart_task(TASK_NGROK, log):
        return False
    recovered = wait_probe(PUBLIC_LIVE, 30)
    log.info("ngrok_restart_result ok=%s", recovered)
    if recovered:
        set_ops_alert("ngrok", False, "info", "Public tunnel recovered")
    return recovered


def main() -> None:
    fd = acquire_lock()
    if fd is None:
        return
    log = logger()
    try:
        if MAINTENANCE.exists():
            log.info("maintenance_mode")
            return
        backend_ok = handle_backend(log)
        public_ok = handle_public(log) if backend_ok else False
        if backend_ok and public_ok:
            log.info("watchdog_ok")
    finally:
        release_lock(fd)


if __name__ == "__main__":
    main()
