#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import filecmp
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
SCHTASKS = str(SYSTEM32 / "schtasks.exe")
POWERSHELL = str(SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe")
ICACLS = str(SYSTEM32 / "icacls.exe")
PYTHON = str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe")
RUNTIME_NGROK = ROOT / "runtime" / "ngrok"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def powershell(script: str) -> str:
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=True,
    )
    return result.stdout.strip()


def find_ngrok_source() -> tuple[Path, Path]:
    script = (
        "$p=Get-AppxPackage ngrok.ngrok; "
        "if(-not $p){throw 'ngrok package not found'}; "
        "$o=[pscustomobject]@{InstallLocation=$p.InstallLocation;"
        "PackageFamilyName=$p.PackageFamilyName}; "
        "$o|ConvertTo-Json -Compress"
    )
    info = json.loads(powershell(script))
    exe = Path(info["InstallLocation"]) / "ngrok.exe"
    cfg = (
        Path(os.environ["LOCALAPPDATA"]) / "Packages" /
        info["PackageFamilyName"] / "LocalCache" / "Local" /
        "ngrok" / "ngrok.yml"
    )
    if not exe.is_file():
        raise FileNotFoundError(f"KhÃ´ng tÃ¬m tháº¥y ngrok.exe: {exe}")
    if not cfg.is_file():
        raise FileNotFoundError(f"KhÃ´ng tÃ¬m tháº¥y cáº¥u hÃ¬nh ngrok: {cfg}")
    return exe, cfg


def copy_if_changed(src: Path, dst: Path) -> bool:
    if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return False
    tmp = dst.with_name(f".{dst.name}.new")
    tmp.unlink(missing_ok=True)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except PermissionError as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"{dst.name} Ä‘ang Ä‘Æ°á»£c sá»­ dá»¥ng vÃ  khÃ¡c báº£n nguá»“n; "
            "dá»«ng MTM_Ngrok rá»“i cháº¡y láº¡i installer"
        ) from exc
    return True


def prepare_ngrok_runtime() -> tuple[Path, Path]:
    exe_src, cfg_src = find_ngrok_source()
    RUNTIME_NGROK.mkdir(parents=True, exist_ok=True)
    exe_dst = RUNTIME_NGROK / "ngrok.exe"
    cfg_dst = RUNTIME_NGROK / "ngrok.yml"
    copy_if_changed(exe_src, exe_dst)
    copy_if_changed(cfg_src, cfg_dst)
    return exe_dst, cfg_dst


def secure_runtime_acl() -> None:
    user = os.environ.get("USERNAME", "Admin")
    subprocess.run([ICACLS, str(RUNTIME_NGROK), "/inheritance:r"], check=True)
    subprocess.run(
        [ICACLS, str(RUNTIME_NGROK), "/grant:r",
         f"{user}:(OI)(CI)F", "SYSTEM:(OI)(CI)F",
         "Administrators:(OI)(CI)F", "/T", "/C"],
        check=True,
    )


def create(name: str, action: str, schedule: list[str]) -> None:
    cmd = [
        SCHTASKS, "/Create", "/TN", name, "/TR", action,
        "/RU", "SYSTEM", "/RL", "HIGHEST", "/F", *schedule,
    ]
    subprocess.run(cmd, check=True)


def harden(name: str, restart_count: int = 0) -> None:
    restart = ""
    if restart_count:
        restart = (
            f" -RestartCount {restart_count} "
            "-RestartInterval (New-TimeSpan -Minutes 1)"
        )
    command = (
        "$s=New-ScheduledTaskSettingsSet "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
        f"{restart}; "
        f"Set-ScheduledTask -TaskName '{name}' -Settings $s | Out-Null"
    )
    subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
    )


def verify_system_task(name: str) -> None:
    raw = subprocess.check_output([SCHTASKS, "/Query", "/TN", name, "/XML"])
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        xml = raw.decode("utf-16", errors="replace")
    else:
        xml = raw.decode("utf-8-sig", errors="replace")
    compact = xml.upper()
    if "S-1-5-18" not in compact and ">SYSTEM<" not in compact:
        raise RuntimeError(f"Task {name} chÆ°a cháº¡y báº±ng SYSTEM")
    print(f"SYSTEM_TASK_OK={name}")


def remove_legacy_autostart() -> None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    path = (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" /
        "Programs" / "Startup" / "MTM-Autostart.cmd"
    )
    path.unlink(missing_ok=True)


def install_system_tasks() -> None:
    if not is_admin():
        raise PermissionError(
            "Cáº§n cháº¡y installer báº±ng Run as administrator Ä‘á»ƒ táº¡o task SYSTEM"
        )
    exe, cfg = prepare_ngrok_runtime()
    secure_runtime_acl()
    subprocess.run([str(exe), "config", "check", "--config", str(cfg)], check=True)

    backend = f'cmd.exe /d /c "{ROOT / "run-backend.bat"}"'
    ngrok = f'cmd.exe /d /c "{ROOT / "run-ngrok.bat"}"'
    watchdog = f'"{PYTHON}" "{ROOT / "scripts" / "watchdog.py"}"'
    backup = f'"{PYTHON}" "{ROOT / "scripts" / "backup_maintenance.py"}"'
    maintenance = (
        f'"{PYTHON}" "{ROOT / "scripts" / "maintenance_cleanup.py"}" --apply'
    )
    specs = (
        ("MTM_Backend", backend, ["/SC", "ONSTART"], 3),
        ("MTM_Ngrok", ngrok, ["/SC", "ONSTART", "/DELAY", "0000:30"], 3),
        ("MTM_Watchdog", watchdog, ["/SC", "MINUTE", "/MO", "2"], 0),
        ("MTM_Backup", backup, ["/SC", "DAILY", "/ST", "03:30"], 0),
        ("MTM_Maintenance", maintenance, ["/SC", "DAILY", "/ST", "04:15"], 0),
    )
    for name, action, schedule, restart_count in specs:
        create(name, action, schedule)
        harden(name, restart_count)
    subprocess.run([SCHTASKS, "/Delete", "/TN", "MTM_GracefulStop", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    remove_legacy_autostart()
    for name, _action, _schedule, _restart_count in specs:
        verify_system_task(name)
    print(f"NGROK_RUNTIME_OK={exe}")
    print("INSTALL_MODE=SYSTEM")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-ngrok", action="store_true")
    parser.add_argument("--apply-system", action="store_true")
    args = parser.parse_args()
    if args.prepare_ngrok:
        exe, cfg = prepare_ngrok_runtime()
        subprocess.run([str(exe), "config", "check", "--config", str(cfg)], check=True)
        print(f"NGROK_RUNTIME_OK={exe}")
        return
    if args.apply_system:
        install_system_tasks()
        return
    parser.error("Chá»n --prepare-ngrok hoáº·c --apply-system")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"INSTALL_FAILED={type(exc).__name__}: {exc}", file=sys.stderr)
        raise
