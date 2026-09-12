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
PYTHON = str(Path(sys.executable))


class MessageDispatchTests(unittest.TestCase):
    def test_normalize_dedupe_and_round_robin_persistence(self):
        with tempfile.TemporaryDirectory(prefix="mtm_message_dispatch_") as td:
            db_path = Path(td) / "dispatch.db"
            env = os.environ.copy()
            env["DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
            env["DATABASE_URL"] = ""
            subprocess.run(
                [PYTHON, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            code = textwrap.dedent("""
                import asyncio, json
                from sqlalchemy import select
                from app.config import settings
                from app.db import AsyncSessionLocal
                from app.message_dispatch import normalize_message_targets, multi_target_message_stream
                from app.models import Account, MessageDispatchItem
                from app.tg_manager import manager

                class FakeClient:
                    def __init__(self): self.sent=[]
                    async def get_entity(self, ref): return ref
                    async def send_message(self, entity, text):
                        self.sent.append((entity, text))
                        return object()

                async def main():
                    targets = normalize_message_targets([
                        '@Alpha', 'alpha', 'https://t.me/Beta', '@beta', '+84 901 234 567'
                    ])
                    assert [t[0] for t in targets] == ['@Alpha', '@Beta', '+84901234567']
                    assert len(targets) == 3

                    async with AsyncSessionLocal() as db:
                        a1=Account(phone='+1001',first_name='A1',session_file='a1',status='connected')
                        a2=Account(phone='+1002',first_name='A2',session_file='a2',status='connected')
                        db.add_all([a1,a2]); await db.commit(); await db.refresh(a1); await db.refresh(a2)
                        accounts=[(a1.id,a1.phone,'A1'),(a2.id,a2.phone,'A2')]
                    c1,c2=FakeClient(),FakeClient()
                    manager._clients[a1.id]=c1; manager._clients[a2.id]=c2
                    settings.RATE_MIN=0; settings.RATE_MAX=0; settings.TG_RPC_TIMEOUT_SECONDS=2
                    events=[]
                    async for chunk in multi_target_message_stream(accounts, targets, 'hello'):
                        events.append(json.loads(chunk))
                    done=[e for e in events if e.get('type')=='done'][-1]
                    assert done['total']==3 and done['success']==3 and done['failed']==0
                    async with AsyncSessionLocal() as db:
                        rows=(await db.execute(select(MessageDispatchItem).order_by(MessageDispatchItem.id))).scalars().all()
                        assert [r.account_id for r in rows] == [a1.id,a2.id,a1.id]
                        assert [r.status for r in rows] == ['ok','ok','ok']
                        assert [r.target for r in rows] == ['@Alpha','@Beta','+84901234567']
                    assert len(c1.sent)==2 and len(c2.sent)==1
                    manager._clients.pop(a1.id,None); manager._clients.pop(a2.id,None)

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, "-c", code], cwd=BACKEND, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
