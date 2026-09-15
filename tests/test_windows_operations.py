import logging
import os
from pathlib import Path
import tempfile
import unittest

from scripts import backup_maintenance as bm
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
    def test_public_launchers_use_maintenance_and_graceful_stop(self):
        start = (ROOT / "start-public.bat").read_text(encoding="utf-8")
        stop = (ROOT / "stop-public.bat").read_text(encoding="utf-8")
        self.assertIn(".maintenance", start)
        self.assertIn("MTM_Backend", start)
        self.assertIn("MTM_Ngrok", start)
        self.assertIn(".maintenance", stop)
        self.assertIn("graceful_stop.py", stop)
        self.assertIn("MTM_Backend", stop)

    def test_task_installer_contract(self):
        src = (ROOT / "scripts" / "install_windows_tasks.py").read_text(encoding="utf-8")
        for name in ("MTM_Backend", "MTM_Ngrok", "MTM_Watchdog", "MTM_Backup"):
            self.assertIn(name, src)
        self.assertIn('"/MO", "2"', src)
        self.assertIn('"03:30"', src)


if __name__ == "__main__":
    unittest.main()
