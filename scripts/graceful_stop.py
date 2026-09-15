#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import subprocess
import time

import psutil


def listener_pid(port: int) -> int | None:
    for conn in psutil.net_connections(kind="tcp"):
        if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
            return conn.pid
    return None


def console_leader(pid: int) -> int:
    current = psutil.Process(pid)
    leader = current.pid
    for parent in current.parents():
        if parent.name().lower() in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
            leader = parent.pid
            break
    return leader


def send_console_ctrl(pid: int) -> None:
    kernel32 = ctypes.windll.kernel32
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(int(pid)):
        raise ctypes.WinError()
    kernel32.SetConsoleCtrlHandler(None, True)
    try:
        if not kernel32.GenerateConsoleCtrlEvent(0, 0):
            raise ctypes.WinError()
        time.sleep(0.25)
    finally:
        kernel32.FreeConsole()
        kernel32.SetConsoleCtrlHandler(None, False)


def wait_stopped(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if listener_pid(port) is None:
            return True
        time.sleep(0.25)
    return listener_pid(port) is None


def stop(port: int, timeout: float, force: bool) -> int:
    pid = listener_pid(port)
    if pid is None:
        print(f"PORT_{port}=already_stopped")
        return 0

    leader = console_leader(pid)
    graceful_sent = False
    try:
        os.kill(leader, signal.CTRL_BREAK_EVENT)
        graceful_sent = True
    except Exception:
        try:
            send_console_ctrl(pid)
            graceful_sent = True
        except Exception as exc:
            print(f"GRACEFUL_SIGNAL_ERROR={type(exc).__name__}")

    if graceful_sent and wait_stopped(port, timeout):
        print(f"PORT_{port}=stopped_gracefully")
        return 0

    if not force:
        print(f"PORT_{port}=still_running")
        return 2
    target = console_leader(pid)
    subprocess.run(
        [os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\taskkill.exe",
         "/PID", str(target), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if wait_stopped(port, 5):
        print(f"PORT_{port}=stopped_forced")
        return 0
    print(f"PORT_{port}=failed_to_stop")
    return 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--no-force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(stop(args.port, args.timeout, not args.no_force))


if __name__ == "__main__":
    main()
