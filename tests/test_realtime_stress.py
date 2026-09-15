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


class RealtimeStressTests(unittest.TestCase):
    def _run(self, code: str):
        with tempfile.TemporaryDirectory(prefix="mtm_realtime_stress_") as td:
            db_path = Path(td) / "stress.db"
            env = os.environ.copy()
            env["DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
            env["DATABASE_URL"] = ""
            env["SESSIONS_DIR"] = str(Path(td) / "sessions")
            subprocess.run(
                [PYTHON, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND, env=env, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run([PYTHON, "-c", textwrap.dedent(code)], cwd=BACKEND, env=env, check=True)
    def test_5000_event_backlog_and_reconnect_cursor(self):
        self._run(r'''
            import asyncio, json
            from app.db import AsyncSessionLocal
            from app.models import RealtimeEvent
            from app.realtime_events import event_stream
            from app.tenant import tenant_scope
            from app.time_utils import utcnow

            UID='90000000-0000-4000-8000-000000000001'
            def event_id(chunk):
                return int([line for line in chunk.splitlines() if line.startswith('id: ')][0][4:])

            async def main():
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        db.add_all([RealtimeEvent(user_id=UID, feature='jobs', level='info', phase='stress',
                            message=f'event-{i}', created_at=utcnow()) for i in range(5000)])
                        await db.commit()
                gen=event_stream(UID, after_id=0, feature='jobs')
                ids=[event_id(await asyncio.wait_for(anext(gen), 2)) for _ in range(5000)]
                assert ids == sorted(ids) and len(set(ids)) == 5000
                cursor=ids[-1]
                await gen.aclose()
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        db.add_all([RealtimeEvent(user_id=UID, feature='jobs', level='info', phase='after_restart',
                            message=f'new-{i}', created_at=utcnow()) for i in range(100)])
                        await db.commit()
                gen=event_stream(UID, after_id=cursor, feature='jobs')
                new_ids=[event_id(await asyncio.wait_for(anext(gen), 2)) for _ in range(100)]
                assert len(new_ids) == 100 and min(new_ids) > cursor
                assert new_ids == sorted(new_ids) and len(set(new_ids)) == 100
                await gen.aclose()
            asyncio.run(main())
        ''')

    def test_overflow_marker_resyncs_from_db(self):
        self._run(r'''
            import asyncio
            from app.db import AsyncSessionLocal
            from app.models import RealtimeEvent
            from app.realtime_events import event_stream, broker, _OVERFLOW
            from app.tenant import tenant_scope
            from app.time_utils import utcnow

            UID='90000000-0000-4000-8000-000000000002'
            async def main():
                gen=event_stream(UID, after_id=0)
                pending=asyncio.create_task(anext(gen))
                await asyncio.sleep(0.05)
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        db.add_all([RealtimeEvent(user_id=UID, feature='proxy', level='info', phase='burst',
                            message=f'event-{i}', created_at=utcnow()) for i in range(700)])
                        await db.commit()
                queues=list(broker._subs.get(UID, ()))
                assert len(queues) == 1
                q=queues[0]
                q.put_nowait(_OVERFLOW)
                first=await asyncio.wait_for(pending, 2)
                assert first.startswith('id: ')
                ids=[int(first.splitlines()[0][4:])]
                for _ in range(699):
                    chunk=await asyncio.wait_for(anext(gen), 2)
                    ids.append(int(chunk.splitlines()[0][4:]))
                assert len(ids)==700 and ids==sorted(ids) and len(set(ids))==700
                await gen.aclose()
                assert UID not in broker._subs
            asyncio.run(main())
        ''')

    def test_50_subscribers_are_tenant_isolated_and_cleaned(self):
        self._run(r'''
            import asyncio
            from app.realtime_events import broker

            async def main():
                groups={}
                for tenant in range(10):
                    uid=f'90000000-0000-4000-8000-{tenant:012d}'
                    groups[uid]=[await broker.subscribe(uid) for _ in range(5)]
                assert sum(len(v) for v in groups.values()) == 50
                for idx, (uid, queues) in enumerate(groups.items()):
                    broker.publish(uid, {'id': idx + 1, 'tenant': uid})
                    for q in queues:
                        payload=await asyncio.wait_for(q.get(), 1)
                        assert payload['tenant'] == uid
                for uid, queues in groups.items():
                    for q in queues:
                        await broker.unsubscribe(uid, q)
                assert not broker._subs
            asyncio.run(main())
        ''')

    def test_stream_cancellation_releases_subscription(self):
        self._run(r'''
            import asyncio
            from app.realtime_events import broker, event_stream

            UID='90000000-0000-4000-8000-000000000003'
            async def main():
                gen=event_stream(UID)
                task=asyncio.create_task(anext(gen))
                await asyncio.sleep(0.05)
                assert UID in broker._subs
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                await gen.aclose()
                await asyncio.sleep(0)
                assert UID not in broker._subs
            asyncio.run(main())
        ''')
    def test_event_store_failure_does_not_break_account_transition(self):
        self._run(r'''
            import asyncio
            import app.realtime_events as realtime_events
            from app.db import AsyncSessionLocal
            from app.models import Account
            from app.tenant import tenant_scope
            from app.tg_manager import manager

            UID='90000000-0000-4000-8000-000000000004'
            class BrokenContext:
                async def __aenter__(self):
                    raise RuntimeError('simulated event-store outage')
                async def __aexit__(self, *args):
                    return False

            async def main():
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        acc=Account(user_id=UID, phone='+84900000999', session_file='stress.session', status='disconnected')
                        db.add(acc); await db.commit(); aid=acc.id
                    realtime_events.AsyncSessionLocal=lambda: BrokenContext()
                    await manager._set_status(aid, 'connecting')
                    async with AsyncSessionLocal() as db:
                        row=await db.get(Account, aid)
                        assert row.status == 'connecting'
            asyncio.run(main())
        ''')
    def test_heartbeat_keeps_idle_stream_alive_without_advancing_cursor(self):
        self._run(r'''
            import asyncio
            import app.realtime_events as realtime_events

            UID='90000000-0000-4000-8000-000000000005'
            async def main():
                realtime_events.HEARTBEAT_SECONDS=0.05
                gen=realtime_events.event_stream(UID, after_id=123)
                first=await asyncio.wait_for(anext(gen), 1)
                second=await asyncio.wait_for(anext(gen), 1)
                assert first.startswith(': heartbeat ')
                assert second.startswith(': heartbeat ')
                assert 'id:' not in first and 'id:' not in second
                await gen.aclose()
                assert UID not in realtime_events.broker._subs
            asyncio.run(main())
        ''')


if __name__ == '__main__':
    unittest.main()

# Extra restart/backpressure acceptance cases are attached dynamically to keep the fixture compact.
def _test_restart_loses_ram_but_db_cursor_recovers(self):
    self._run(r'''
        import asyncio
        import app.realtime_events as re
        from app.tenant import tenant_scope

        UID='90000000-0000-4000-8000-000000000006'
        def eid(chunk): return int(chunk.splitlines()[0][4:])
        async def main():
            with tenant_scope(UID):
                for i in range(20):
                    await re.emit_event('jobs','info','restart',f'before-{i}', strict=True)
            gen=re.event_stream(UID, after_id=0)
            first=[eid(await asyncio.wait_for(anext(gen),2)) for _ in range(10)]
            cursor=first[-1]; await gen.aclose()
            re.broker=re.EventBroker()
            gen=re.event_stream(UID, after_id=cursor)
            recovered=[eid(await asyncio.wait_for(anext(gen),2)) for _ in range(10)]
            assert len(recovered)==10 and min(recovered)>cursor
            with tenant_scope(UID):
                for i in range(5):
                    await re.emit_event('jobs','success','live',f'after-{i}', strict=True)
            live=[eid(await asyncio.wait_for(anext(gen),2)) for _ in range(5)]
            assert min(live)>recovered[-1]
            assert recovered+live == sorted(recovered+live)
            await gen.aclose()
            assert UID not in re.broker._subs
        asyncio.run(main())
    ''')


def _test_burst_backpressure_is_bounded_for_50_subscribers(self):
    self._run(r'''
        import asyncio
        from app.realtime_events import broker, QUEUE_SIZE, _OVERFLOW

        async def main():
            groups={}
            for tenant in range(10):
                uid=f'91000000-0000-4000-8000-{tenant:012d}'
                groups[uid]=[await broker.subscribe(uid) for _ in range(5)]
            for uid in groups:
                for i in range(800):
                    broker.publish(uid, {'id': i+1, 'tenant': uid})
            for uid, queues in groups.items():
                for q in queues:
                    assert 1 <= q.qsize() <= QUEUE_SIZE
                    rows=[]
                    while not q.empty():
                        rows.append(q.get_nowait())
                    assert any(row is _OVERFLOW for row in rows)
                    assert all(row is _OVERFLOW or row.get('tenant') == uid for row in rows)
                    await broker.unsubscribe(uid, q)
            assert not broker._subs
        asyncio.run(main())
    ''')


RealtimeStressTests.test_restart_loses_ram_but_db_cursor_recovers = _test_restart_loses_ram_but_db_cursor_recovers
RealtimeStressTests.test_burst_backpressure_is_bounded_for_50_subscribers = _test_burst_backpressure_is_bounded_for_50_subscribers
