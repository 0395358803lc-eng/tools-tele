#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SCHTASKS = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe")
TASKS = ("MTM_Backend", "MTM_Ngrok", "MTM_Watchdog", "MTM_Backup", "MTM_Maintenance")
LOCAL_READY = "http://127.0.0.1:8000/api/health/ready"
PUBLIC_LIVE = "https://bony-issue-ramrod.ngrok-free.dev/api/health/live"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def task_xml(name: str) -> ET.Element:
    raw = subprocess.check_output(
        [SCHTASKS, "/Query", "/TN", name, "/XML"],
        text=True, encoding="utf-16", errors="replace",
    )
    return ET.fromstring(raw)


def check_task(name: str) -> bool:
    root = task_xml(name)
    user = root.findtext(".//t:Principal/t:UserId", default="", namespaces=NS)
    logon = root.findtext(".//t:Principal/t:LogonType", default="", namespaces=NS)
    is_system = user.upper() == "S-1-5-18" or user.upper() == "SYSTEM"
    ok = is_system and logon.lower() == "serviceaccount"
    trigger_ok = True
    if name in {"MTM_Backend", "MTM_Ngrok"}:
        trigger_ok = root.find(".//t:BootTrigger", NS) is not None
    ok = ok and trigger_ok
    print(
        f"TASK={name} SYSTEM={is_system} LOGON={logon or '-'} "
        f"BOOT_TRIGGER={trigger_ok} OK={ok}"
    )
    return ok


def http_ok(url: str) -> bool:
    try:
        with urlopen(url, timeout=10) as response:
            return response.status == 200
    except Exception:
        return False


def main() -> int:
    checks = [check_task(name) for name in TASKS]
    local_ok = http_ok(LOCAL_READY)
    public_ok = http_ok(PUBLIC_LIVE)
    print(f"LOCAL_READY={local_ok}")
    print(f"PUBLIC_LIVE={public_ok}")
    runtime_ok = (
        (ROOT / "runtime" / "ngrok" / "ngrok.exe").is_file()
        and (ROOT / "runtime" / "ngrok" / "ngrok.yml").is_file()
    )
    print(f"NGROK_RUNTIME={runtime_ok}")
    ok = all(checks) and local_ok and public_ok and runtime_ok
    print(f"BOOT_MODE_ACCEPTANCE={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
