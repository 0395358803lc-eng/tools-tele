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


class RealtimeEventTests(unittest.TestCase):
    def _run(self, code: str):
        with tempfile.TemporaryDirectory(prefix="mtm_events_") as td:
            db_path = Path(td) / "events.db"
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

    def test_redaction_and_tenant_isolation(self):
        self._run(r'''
            import asyncio
            from sqlalchemy import select
            from app.db import AsyncSessionLocal
            from app.models import RealtimeEvent
            from app.realtime_events import emit_event, query_events
            from app.tenant import tenant_scope

            A='11111111-1111-4111-8111-111111111111'
            B='22222222-2222-4222-8222-222222222222'

            async def main():
                with tenant_scope(A):
                    await emit_event('messaging','info','send','token=abc api_hash=xyz password=q json={"password":"jsonpw","api_hash":"jsonhash"}',
                        metadata={'password':'pw','safe':'ok','nested':{'session':'blob'}}, strict=True)
                with tenant_scope(B):
                    await emit_event('proxy','error','connect','proxy_password=hidden', strict=True)
                rows=await query_events(A, limit=10)
                assert len(rows)==1 and rows[0]['feature']=='messaging'
                assert all(x not in rows[0]['message'] for x in ('abc','xyz','jsonpw','jsonhash'))
                assert rows[0]['metadata']['password']=='[redacted]'
                assert rows[0]['metadata']['nested']['session']=='[redacted]'
                with tenant_scope(A):
                    async with AsyncSessionLocal() as db:
                        visible=(await db.execute(select(RealtimeEvent))).scalars().all()
                        assert len(visible)==1 and visible[0].user_id==A
            asyncio.run(main())
        ''')

    def test_stream_cursor_reconnect_and_heartbeat_contract(self):
        self._run(r'''
            import asyncio, json
            from app.realtime_events import emit_event, event_stream
            from app.tenant import tenant_scope

            UID='33333333-3333-4333-8333-333333333333'

            def parse(chunk):
                line=[x for x in chunk.splitlines() if x.startswith('data: ')][0]
                return json.loads(line[6:])

            async def main():
                with tenant_scope(UID):
                    first=await emit_event('jobs','info','created','one', strict=True)
                    second=await emit_event('jobs','success','checkpoint','two', strict=True)
                gen=event_stream(UID, after_id=first['id'])
                got=parse(await asyncio.wait_for(anext(gen), 2))
                assert got['id']==second['id']
                await gen.aclose()

                gen=event_stream(UID, after_id=second['id'])
                task=asyncio.create_task(anext(gen))
                await asyncio.sleep(0.05)
                with tenant_scope(UID):
                    third=await emit_event('jobs','warning','retry','three', strict=True)
                got=parse(await asyncio.wait_for(task, 2))
                assert got['id']==third['id'] and got['phase']=='retry'
                await gen.aclose()
            asyncio.run(main())
        ''')

    def test_broker_queue_is_bounded(self):
        self._run(r'''
            import asyncio
            from app.realtime_events import broker, QUEUE_SIZE, _OVERFLOW

            async def main():
                uid='44444444-4444-4444-8444-444444444444'
                q=await broker.subscribe(uid)
                for i in range(1, QUEUE_SIZE+90):
                    broker.publish(uid, {'id':i})
                assert 1 <= q.qsize() <= QUEUE_SIZE
                first=await q.get()
                assert first is _OVERFLOW
                await broker.unsubscribe(uid,q)
            asyncio.run(main())
        ''')

    def test_stream_catches_up_more_than_one_page(self):
        self._run(r'''
            import asyncio
            from app.db import AsyncSessionLocal
            from app.models import RealtimeEvent
            from app.realtime_events import event_stream
            from app.tenant import tenant_scope
            from app.time_utils import utcnow
            UID='66666666-6666-4666-8666-666666666666'
            async def main():
                with tenant_scope(UID):
                    async with AsyncSessionLocal() as db:
                        db.add_all([RealtimeEvent(user_id=UID,feature='jobs',level='info',phase='bulk',message=f'e{{i}}',created_at=utcnow()) for i in range(520)])
                        await db.commit()
                gen=event_stream(UID, after_id=0, feature='jobs')
                chunks=[]
                for _ in range(520):
                    chunks.append(await asyncio.wait_for(anext(gen), 2))
                assert len(chunks)==520
                ids=[int([x for x in c.splitlines() if x.startswith('id: ')][0][4:]) for c in chunks]
                assert ids==sorted(ids) and len(set(ids))==520
                await gen.aclose()
            asyncio.run(main())
        ''')

    def test_history_filters_and_router_contract(self):
        self._run(r'''
            import asyncio
            from app.realtime_events import emit_event, query_events
            from app.tenant import tenant_scope

            UID='55555555-5555-4555-8555-555555555555'
            async def main():
                with tenant_scope(UID):
                    await emit_event('proxy','info','test','primary ok', account_id=7, strict=True)
                    await emit_event('jobs','error','worker','worker failed', job_id='job-x', strict=True)
                    await emit_event('proxy','warning','failover','fallback active', account_id=7, strict=True)
                proxy=await query_events(UID, feature='proxy', account_id=7, limit=10)
                assert len(proxy)==2 and all(x['feature']=='proxy' for x in proxy)
                errors=await query_events(UID, level='error', search='worker', limit=10)
                assert len(errors)==1 and errors[0]['job_id']=='job-x'
            asyncio.run(main())
        ''')
        source=(ROOT/'backend/app/routers/events.py').read_text(encoding='utf-8')
        main=(ROOT/'backend/app/main.py').read_text(encoding='utf-8')
        self.assertIn('text/event-stream', source)
        self.assertIn('last-event-id', source)
        self.assertIn('X-Accel-Buffering', source)
        self.assertIn('app.include_router(events.router', main)


if __name__ == '__main__':
    unittest.main()
