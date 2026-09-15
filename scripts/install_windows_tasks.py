#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
SCHTASKS = str(SYSTEM32 / "schtasks.exe")
POWERSHELL = str(SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe")
PYTHON = str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe")


def create(name: str, action: str, schedule: list[str]) -> None:
    cmd = [SCHTASKS, "/Create", "/TN", name, "/TR", action, "/F", *schedule]
    subprocess.run(cmd, check=True)


def harden(name: str) -> None:
    command = (
        "$s=New-ScheduledTaskSettingsSet "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Set-ScheduledTask -TaskName '{name}' -Settings $s | Out-Null"
    )
    subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command], check=True)


def main() -> None:
    backend = f'cmd.exe /d /c {ROOT / "run-backend.bat"}'
    ngrok = f'cmd.exe /d /c {ROOT / "run-ngrok.bat"}'
    watchdog = f'{PYTHON} {ROOT / "scripts" / "watchdog.py"}'
    backup = f'{PYTHON} {ROOT / "scripts" / "backup_maintenance.py"}'
    maintenance = f'{PYTHON} {ROOT / "scripts" / "maintenance_cleanup.py"} --apply'

    specs = (
        ("MTM_Backend", backend, ["/SC", "DAILY", "/ST", "23:59"]),
        ("MTM_Ngrok", ngrok, ["/SC", "DAILY", "/ST", "23:59"]),
        ("MTM_Watchdog", watchdog, ["/SC", "MINUTE", "/MO", "2"]),
        ("MTM_Backup", backup, ["/SC", "DAILY", "/ST", "03:30"]),
        ("MTM_Maintenance", maintenance, ["/SC", "DAILY", "/ST", "04:15"]),
    )
    for name, action, schedule in specs:
        create(name, action, schedule)
        harden(name)

    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True, exist_ok=True)
    autostart = startup / "MTM-Autostart.cmd"
    autostart.write_text(
        '@echo off\n'
        'schtasks /Run /TN MTM_Backend >nul 2>nul\n'
        'powershell -NoProfile -Command "Start-Sleep -Seconds 8"\n'
        'schtasks /Run /TN MTM_Ngrok >nul 2>nul\n',
        encoding="utf-8",
    )

    for name, _action, _schedule in specs:
        result = subprocess.run(
            [SCHTASKS, "/Query", "/TN", name, "/FO", "LIST"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise SystemExit(f"Không thể xác minh task {name}")
        print(f"TASK_OK={name}")
    print(f"AUTOSTART_OK={autostart}")


if __name__ == "__main__":
    main()
