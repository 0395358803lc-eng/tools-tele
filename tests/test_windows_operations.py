import logging
import os
from pathlib import Path
import tempfile
import unittest

from scripts import backup_maintenance as bm
from scripts import install_windows_tasks as iwt
from scripts import watchdog as wd

ROOT = Path(__file__).resolve().parents[1]


class WindowsOperationsTests(unittest.TestCase):
    def test_backup_prune_keeps_newest_seven(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            for i in range(10):
                p = folder / f"b{i}.tar.gz"
                p.write_bytes(str(i).encode())
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual(bm.prune(folder, 7), 3)
            names = {p.name for p in folder.glob("*.tar.gz")}
            self.assertEqual(names, {f"b{i}.tar.gz" for i in range(3, 10)})

    def test_maintenance_mode_skips_watchdog_probes(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / ".maintenance"
            marker.write_text("maintenance")
            old = (wd.MAINTENANCE, wd.acquire_lock, wd.release_lock, wd.logger, wd.probe)
            try:
                wd.MAINTENANCE = marker
                wd.acquire_lock = lambda: 1
                wd.release_lock = lambda _fd: None
                wd.logger = lambda: logging.getLogger("watchdog-maintenance-test")
                wd.probe = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("probe called"))
                wd.main()
            finally:
                wd.MAINTENANCE, wd.acquire_lock, wd.release_lock, wd.logger, wd.probe = old

    def test_restart_circuit_breaker_limits_flapping(self):
        with tempfile.TemporaryDirectory() as td:
            old_state, old_log = wd.STATE, wd.LOG_DIR
            try:
                wd.LOG_DIR = Path(td)
                wd.STATE = Path(td) / "watchdog-state.json"
                self.assertTrue(wd.permit_restart("MTM_Backend", now=100.0))
                self.assertTrue(wd.permit_restart("MTM_Backend", now=101.0))
                self.assertTrue(wd.permit_restart("MTM_Backend", now=102.0))
                self.assertFalse(wd.permit_restart("MTM_Backend", now=103.0))
                self.assertTrue(
                    wd.permit_restart(
                        "MTM_Backend", now=100.0 + wd.RESTART_WINDOW_SECONDS + 1
                    )
                )
            finally:
                wd.STATE, wd.LOG_DIR = old_state, old_log

    def test_readiness_category_detects_database_failure(self):
        self.assertEqual(wd.readiness_category({"failed_checks": ["postgresql"]}), "database")
        self.assertEqual(wd.readiness_category({"failed_checks": ["other"]}), "backend")

    def test_public_launchers_use_maintenance_and_graceful_stop(self):
        start = (ROOT / "start-public.bat").read_text(encoding="utf-8")
        stop = (ROOT / "stop-public.bat").read_text(encoding="utf-8")
        self.assertIn(".maintenance", start)
        self.assertIn("MTM_Backend", start)
        self.assertIn("MTM_Ngrok", start)
        self.assertIn(".maintenance", stop)
        self.assertIn("Verb RunAs", stop)
        self.assertIn("MTM_Backend", stop)

    def test_copy_if_changed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src.bin"
            dst = root / "dst.bin"
            src.write_bytes(b"same")
            dst.write_bytes(b"same")
            before = dst.stat().st_mtime_ns
            self.assertFalse(iwt.copy_if_changed(src, dst))
            self.assertEqual(dst.stat().st_mtime_ns, before)
            src.write_bytes(b"changed")
            self.assertTrue(iwt.copy_if_changed(src, dst))
            self.assertEqual(dst.read_bytes(), b"changed")

    def test_task_installer_contract(self):
        src = (ROOT / "scripts" / "install_windows_tasks.py").read_text(encoding="utf-8")
        for name in ("MTM_Backend", "MTM_Ngrok", "MTM_Watchdog", "MTM_Backup"):
            self.assertIn(name, src)
        self.assertIn('"/RU", "SYSTEM"', src)
        self.assertIn('"/SC", "ONSTART"', src)
        self.assertIn("RestartCount", src)
        self.assertIn("MultipleInstances IgnoreNew", src)
        self.assertIn("AllowStartIfOnBatteries", src)
        self.assertIn("runtime", src)

    def test_ngrok_launcher_waits_for_backend_and_uses_runtime_config(self):
        src = (ROOT / "run-ngrok.bat").read_text(encoding="utf-8")
        self.assertIn("runtime\\ngrok\\ngrok.exe", src)
        self.assertIn("runtime\\ngrok\\ngrok.yml", src)
        self.assertIn("/api/health/ready", src)
        self.assertIn("--config=", src)

    def test_elevated_installer_and_boot_verifier_present(self):
        elevate = (ROOT / "install-system-tasks.bat").read_text(encoding="utf-8")
        verify = (ROOT / "scripts" / "verify_windows_boot_mode.py").read_text(encoding="utf-8")
        self.assertIn("Verb RunAs", elevate)
        self.assertIn("--apply-system", elevate)
        self.assertIn("BootTrigger", verify)
        self.assertIn("BOOT_MODE_ACCEPTANCE", verify)


if __name__ == "__main__":
    unittest.main()
