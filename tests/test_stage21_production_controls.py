from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = str(BACKEND / ".venv" / "Scripts" / "python.exe") if (BACKEND / ".venv" / "Scripts" / "python.exe").exists() else sys.executable


class Stage21ProductionControlsTests(unittest.TestCase):
    def test_safe_message_retry_contract(self):
        src = (BACKEND / "app" / "routers" / "jobs.py").read_text(encoding="utf-8")
        self.assertIn('MessageDispatchItem.error_code == "FloodWaitError"', src)
        self.assertIn("MessageDispatchItem.attempts == 0", src)
        self.assertIn('"safe_retry": "pre_send_flood_wait"', src)
        self.assertNotIn('error_code == "TimeoutError"', src[src.index('retry_message_job'):src.index('@router.post("/{job_id}/retry")')])

    def test_failover_never_uses_floodwait(self):
        src = (BACKEND / "app" / "tg_manager.py").read_text(encoding="utf-8")
        self.assertIn('info.category == "network"', src)
        self.assertIn('info.category != "flood_wait"', src)
        self.assertIn('"proxy_error"', src)
        self.assertIn("_mark_deactivated", src)
    def test_frontend_and_export_contracts(self):
        api = (ROOT / "frontend" / "src" / "lib" / "api.js").read_text(encoding="utf-8")
        phone = (ROOT / "frontend" / "src" / "tabs" / "PhoneCheckTab.jsx").read_text(encoding="utf-8")
        inbox = (ROOT / "frontend" / "src" / "tabs" / "InboxTab.jsx").read_text(encoding="utf-8")
        proxy = (ROOT / "frontend" / "src" / "tabs" / "ProxyTab.jsx").read_text(encoding="utf-8")
        self.assertIn("downloadPhoneCheckExport", api)
        self.assertIn("rebalancePhoneCheckJob", api)
        self.assertIn("retryMessageJob", api)
        self.assertIn("testFallbackProxy", api)
        self.assertIn("XLSX tất cả", phone)
        self.assertIn("Phân phối lại", phone)
        self.assertIn("Đọc tất cả", inbox)
        self.assertIn("Proxy dự phòng", proxy)
        route = (BACKEND / "app" / "routers" / "phone_checks.py").read_text(encoding="utf-8")
        self.assertIn('export.xlsx', route)

    def test_phone_check_rebalance_moves_only_safe_pending_items(self):
        with tempfile.TemporaryDirectory(prefix="mtm_rebalance_") as td:
            base = Path(td)
            env = os.environ.copy()
            env.update({
                "DB_URL": f"sqlite+aiosqlite:///{base / 'test.db'}",
                "DATABASE_URL": "",
                "SESSIONS_DIR": str(base / "sessions"),
            })
            (base / "sessions").mkdir()
            subprocess.run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent('''
                import asyncio
                from app.db import AsyncSessionLocal
                from app.models import Account, BulkJob, PhoneCheckAccount, PhoneCheckItem
                from app.routers.phone_checks import rebalance_phone_check_job, manager
                from app.tenant import set_tenant_id
                uid="00000000-0000-4000-8000-000000000001"; set_tenant_id(uid)
''')
            code += textwrap.dedent('''
                async def main():
                    async with AsyncSessionLocal() as db:
                        a1=Account(phone="+1001",session_file="a1",status="connected")
                        a2=Account(phone="+1002",session_file="a2",status="network_error")
                        db.add_all([a1,a2]); await db.commit(); await db.refresh(a1); await db.refresh(a2)
                        job=BulkJob(id="j1",type="phone_check",status="running",total=2,pending=2)
                        db.add(job); await db.commit()
                        db.add_all([
                            PhoneCheckAccount(job_id="j1",account_id=a1.id,status="running",assigned_total=1),
                            PhoneCheckAccount(job_id="j1",account_id=a2.id,status="waiting_connection",assigned_total=1),
                            PhoneCheckItem(job_id="j1",account_id=a1.id,original_phone="+84901",normalized_phone="+84901",dedupe_key="1",status="queued"),
                            PhoneCheckItem(job_id="j1",account_id=a2.id,original_phone="+84902",normalized_phone="+84902",dedupe_key="2",status="queued"),
                        ])
                        await db.commit()
                    original=manager.get
                    manager.get=lambda aid: object() if aid==a1.id else None
                    try:
                        async with AsyncSessionLocal() as db:
                            result=await rebalance_phone_check_job("j1",db)
                            assert result["moved"]==1, result
                            items=(await db.execute(__import__('sqlalchemy').select(PhoneCheckItem).order_by(PhoneCheckItem.id))).scalars().all()
                            assert [x.account_id for x in items]==[a1.id,a1.id]
                            rows=(await db.execute(__import__('sqlalchemy').select(PhoneCheckAccount).order_by(PhoneCheckAccount.id))).scalars().all()
                            assert rows[0].assigned_total==2 and rows[1].assigned_total==0
                    finally: manager.get=original
                asyncio.run(main())
            ''')
            subprocess.run([PYTHON, "-c", code], cwd=BACKEND, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
