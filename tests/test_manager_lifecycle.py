from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
WORKSPACE = ROOT.parents[1]
VENV = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV if VENV.exists() else Path(sys.executable))


class ManagerLifecycleTests(unittest.TestCase):
    def _env(self, db_path: Path, sessions: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            'DB_URL': f'sqlite+aiosqlite:///{db_path}',
            'DATABASE_URL': '',
            'SESSIONS_DIR': str(sessions),
            'PENDING_LOGIN_TTL_SECONDS': '60',
            'QR_PENDING_TTL_SECONDS': '60',
        })
        return env

    def test_stale_pending_and_qr_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='mtm_pending_cleanup_') as td:
            base = Path(td)
            db_path = base / 'cleanup.db'
            sessions = base / 'sessions'
            sessions.mkdir()
            env = self._env(db_path, sessions)
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from datetime import datetime, timedelta
                from pathlib import Path
                from app.config import settings
                from app.tg_manager import TgClientManager
                from app.time_utils import utcnow

                class FakeClient:
                    def __init__(self): self.disconnected = 0
                    async def disconnect(self): self.disconnected += 1

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    mgr = TgClientManager()
                    otp = FakeClient()
                    qr = FakeClient()
                    qr_task = asyncio.create_task(asyncio.sleep(3600))
                    session_base = str(Path(settings.SESSIONS_DIR) / 'qr_stale')
                    Path(session_base + '.session').write_bytes(b'temp')
                    stale = utcnow() - timedelta(seconds=120)
                    uid='00000000-0000-4000-8000-000000000001'
                    pending_key=f'{uid}|+1000'
                    mgr._pending[pending_key] = {
                        'client': otp, 'owner_id': uid, 'phone_code_hash': 'x', 'needs_2fa': False, 'created_at': stale,
                    }
                    mgr._qr_pending['stale'] = {
                        'client': qr, 'owner_id': uid, 'wait_task': qr_task, 'created_at': stale,
                        'session_path': session_base, 'authorized': False,
                        'needs_2fa': False, 'error': None, 'me': None, 'qr_login': object(),
                    }
                    await mgr.cleanup_pending()
                    assert pending_key not in mgr._pending
                    assert 'stale' not in mgr._qr_pending
                    assert otp.disconnected == 1
                    assert qr.disconnected == 1
                    assert qr_task.cancelled()
                    assert not Path(session_base + '.session').exists()

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_qr_recreate_and_cancel_do_not_leak_cancelled_error(self):
        with tempfile.TemporaryDirectory(prefix='mtm_qr_cancel_') as td:
            base = Path(td)
            db_path = base / 'qr.db'
            sessions = base / 'sessions'
            sessions.mkdir()
            env = self._env(db_path, sessions)
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from datetime import datetime, timedelta
                from pathlib import Path
                from app.config import settings
                from app.tg_manager import TgClientManager

                class FakeQR:
                    url = 'tg://login?token=test'
                    expires = None
                    async def wait(self): await asyncio.sleep(3600)

                class FakeClient:
                    def __init__(self): self.disconnected = 0; self.qr_calls = 0
                    async def qr_login(self): self.qr_calls += 1; return FakeQR()
                    async def disconnect(self): self.disconnected += 1

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    mgr = TgClientManager()
                    cli = FakeClient()
                    old = asyncio.create_task(asyncio.sleep(3600))
                    session_base = str(Path(settings.SESSIONS_DIR) / 'qr_live')
                    Path(session_base + '.session').write_bytes(b'temp')
                    uid='00000000-0000-4000-8000-000000000001'
                    mgr._qr_pending['q'] = {
                        'client': cli, 'owner_id': uid, 'qr_login': FakeQR(), 'wait_task': old,
                        'needs_2fa': False, 'authorized': False, 'error': None,
                        'me': None, 'session_path': session_base,
                        'created_at': datetime.now() - timedelta(seconds=30),
                    }
                    result = await mgr.qr_recreate('q')
                    assert result['qr_id'] == 'q'
                    assert old.cancelled()
                    assert cli.qr_calls == 1
                    new_task = mgr._qr_pending['q']['wait_task']
                    await mgr.qr_cancel('q')
                    assert new_task.cancelled()
                    assert cli.disconnected == 1
                    assert 'q' not in mgr._qr_pending
                    assert not Path(session_base + '.session').exists()

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_startup_filters_terminal_and_deleted_accounts_and_tracks_task(self):
        with tempfile.TemporaryDirectory(prefix='mtm_startup_filter_') as td:
            base = Path(td)
            db_path = base / 'startup.db'
            sessions = base / 'sessions'
            sessions.mkdir()
            env = self._env(db_path, sessions)
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from datetime import datetime
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tg_manager import TgClientManager

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        active = Account(phone='active', session_file='a', status='connected')
                        banned = Account(phone='banned', session_file='b', status='banned')
                        deactivated = Account(phone='deactivated', session_file='d', status='deactivated')
                        deleted = Account(phone='deleted', session_file='x', status='connected', deleted_at=datetime.now())
                        db.add_all([active, banned, deactivated, deleted])
                        await db.commit()
                        for row in (active, banned, deactivated, deleted): await db.refresh(row)
                    mgr = TgClientManager()
                    started = []
                    sync_started = asyncio.Event()
                    sync_cancelled = asyncio.Event()
                    async def fake_start(acc): started.append(acc.id); return object()
                    async def fake_sync():
                        sync_started.set()
                        try: await asyncio.sleep(3600)
                        except asyncio.CancelledError:
                            sync_cancelled.set(); raise
                    mgr.start_client = fake_start
                    mgr.sync_session_folder = fake_sync
                    await mgr.startup_load_all()
                    await asyncio.wait_for(sync_started.wait(), timeout=1)
                    assert started == [active.id], started
                    assert len(mgr._background_tasks) == 1
                    await mgr.shutdown()
                    assert sync_cancelled.is_set()
                    assert not mgr._background_tasks

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_startup_100_accounts_respects_concurrency(self):
        with tempfile.TemporaryDirectory(prefix='mtm_startup_load_') as td:
            base = Path(td)
            db_path = base / 'startup100.db'
            sessions = base / 'sessions'
            sessions.mkdir()
            env = self._env(db_path, sessions)
            env['STARTUP_CONCURRENCY'] = '10'
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tg_manager import TgClientManager

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        rows=[Account(phone=f'start-{i:03d}',session_file=f's{i}',status='connected') for i in range(100)]
                        db.add_all(rows); await db.commit()
                    mgr=TgClientManager()
                    current=0; max_seen=0; started=0
                    lock=asyncio.Lock()
                    async def fake_start(acc):
                        nonlocal current,max_seen,started
                        async with lock:
                            current += 1; started += 1; max_seen=max(max_seen,current)
                        try:
                            await asyncio.sleep(0.01)
                            return object()
                        finally:
                            async with lock: current -= 1
                    async def fake_sync(): return {'success':0,'failed':0,'skipped':0}
                    mgr.start_client=fake_start
                    mgr.sync_session_folder=fake_sync
                    await mgr.startup_load_all()
                    await asyncio.sleep(0)
                    assert started==100, started
                    assert 2 <= max_seen <= 10, max_seen
                    await mgr.shutdown()
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_flood_wait_expiry_and_reconnect_are_persisted(self):
        with tempfile.TemporaryDirectory(prefix='mtm_flood_reconnect_') as td:
            base=Path(td)
            db_path=base/'state.db'
            sessions=base/'sessions'; sessions.mkdir()
            env=self._env(db_path,sessions)
            subprocess.run([PYTHON,'-m','alembic','upgrade','head'],cwd=BACKEND,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            code=textwrap.dedent("""
                import asyncio
                from datetime import timedelta
                from sqlalchemy import select
                from app.db import AsyncSessionLocal
                from app.models import Account, AccountStatusHistory
                from app.tg_manager import TgClientManager
                from app.time_utils import utcnow

                class ReconnectClient:
                    def __init__(self): self.connected=False; self.connect_calls=0
                    def is_connected(self): return self.connected
                    async def connect(self): self.connect_calls += 1; self.connected=True
                    async def is_user_authorized(self): return True

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        acc=Account(phone='state-test',session_file='s',status='connected')
                        db.add(acc); await db.commit(); await db.refresh(acc); aid=acc.id
                    mgr=TgClientManager()
                    await mgr.mark_flood_wait(aid, 120)
                    remaining=await mgr.flood_wait_remaining(aid)
                    assert 1 <= remaining <= 120
                    async with AsyncSessionLocal() as db:
                        acc=await db.get(Account,aid)
                        assert acc.status=='flood_wait'
                        assert acc.last_error_type=='FloodWaitError'
                        acc.flood_wait_until=utcnow()-timedelta(seconds=1)
                        await db.commit()
                    assert await mgr.flood_wait_remaining(aid)==0
                    async with AsyncSessionLocal() as db:
                        acc=await db.get(Account,aid)
                        assert acc.status=='connected' and acc.flood_wait_until is None
                    cli=ReconnectClient(); mgr._clients[aid]=cli
                    await mgr.refresh_status_all()
                    async with AsyncSessionLocal() as db:
                        acc=await db.get(Account,aid)
                        histories=(await db.execute(select(AccountStatusHistory).where(AccountStatusHistory.account_id==aid))).scalars().all()
                        assert acc.reconnect_count==1
                        assert acc.status=='connected'
                        assert cli.connect_calls==1
                        assert any(h.status=='flood_wait' for h in histories)
                        assert any(h.status=='connected' and h.detail=='Đã hết thời gian FloodWait' for h in histories)
                    mgr._clients.clear()
                asyncio.run(main())
            """)
            subprocess.run([PYTHON,'-c',code],cwd=BACKEND,env=env,check=True)

    def test_retryable_network_failures_use_exponential_backoff(self):
        with tempfile.TemporaryDirectory(prefix='mtm_reconnect_backoff_') as td:
            base=Path(td)
            db_path=base/'backoff.db'
            sessions=base/'sessions'; sessions.mkdir()
            env=self._env(db_path,sessions)
            env.update({
                'RECONNECT_BACKOFF_BASE_SECONDS':'10',
                'RECONNECT_BACKOFF_MAX_SECONDS':'60',
                'RECONNECT_BACKOFF_JITTER_RATIO':'0',
            })
            subprocess.run([PYTHON,'-m','alembic','upgrade','head'],cwd=BACKEND,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            code=textwrap.dedent("""
                import asyncio, time
                from app.config import settings
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tg_manager import TgClientManager

                class FailingClient:
                    def __init__(self): self.connect_calls=0
                    def is_connected(self): return False
                    async def connect(self):
                        self.connect_calls += 1
                        raise TimeoutError('network down')
                    async def is_user_authorized(self): return True

                class GoodClient:
                    def __init__(self): self.connected=False; self.connect_calls=0
                    def is_connected(self): return self.connected
                    async def connect(self): self.connect_calls += 1; self.connected=True
                    async def is_user_authorized(self): return True

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        acc=Account(phone='backoff-test',session_file='s',status='connected')
                        db.add(acc); await db.commit(); await db.refresh(acc); aid=acc.id
                    mgr=TgClientManager(); bad=FailingClient(); mgr._clients[aid]=bad
                    assert settings.RECONNECT_BACKOFF_BASE_SECONDS == 10
                    await mgr.refresh_status_all()
                    first_not_before=mgr._reconnect_not_before[aid]
                    assert bad.connect_calls==1
                    assert mgr._reconnect_failures[aid]==1
                    remaining1=first_not_before-time.monotonic()
                    assert 8.5 <= remaining1 <= 10.5, remaining1
                    async with AsyncSessionLocal() as db:
                        row=await db.get(Account,aid)
                        assert row.reconnect_count==1 and row.status=='network_error'

                    await mgr.refresh_status_all()
                    assert bad.connect_calls==1
                    async with AsyncSessionLocal() as db:
                        row=await db.get(Account,aid)
                        assert row.reconnect_count==1

                    mgr._reconnect_not_before[aid]=time.monotonic()-1
                    await mgr.refresh_status_all()
                    assert bad.connect_calls==2
                    assert mgr._reconnect_failures[aid]==2
                    remaining2=mgr._reconnect_not_before[aid]-time.monotonic()
                    assert 18.5 <= remaining2 <= 20.5, remaining2

                    good=GoodClient(); mgr._clients[aid]=good
                    mgr._reconnect_not_before[aid]=time.monotonic()-1
                    await mgr.refresh_status_all()
                    assert good.connect_calls==1
                    assert aid not in mgr._reconnect_failures
                    assert aid not in mgr._reconnect_not_before
                    async with AsyncSessionLocal() as db:
                        row=await db.get(Account,aid)
                        assert row.status=='connected' and row.reconnect_count==3
                    mgr._clients.clear()
                asyncio.run(main())
            """)
            subprocess.run([PYTHON,'-c',code],cwd=BACKEND,env=env,check=True)


if __name__ == '__main__':
    unittest.main()
