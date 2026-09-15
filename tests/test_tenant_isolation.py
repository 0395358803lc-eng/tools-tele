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
PYTHON = str(Path(sys.executable))
A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'


def migrated_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({'DB_URL': f'sqlite+aiosqlite:///{path}', 'DATABASE_URL': ''})
    subprocess.run(
        [PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return env


class TenantIsolationTests(unittest.TestCase):
    def test_orm_blocks_cross_tenant_crud(self):
        with tempfile.TemporaryDirectory(prefix='mtm_tenant_guard_') as td:
            env = migrated_env(Path(td) / 'guard.db')
            code = textwrap.dedent(f'''\
                import asyncio
                from sqlalchemy import delete, select, update
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tenant import system_scope, tenant_scope
                A={A!r}; B={B!r}

                async def main():
                    with tenant_scope(A):
                        async with AsyncSessionLocal() as db:
                            a=Account(phone='+1001',session_file='a',status='connected')
                            db.add(a); await db.commit(); await db.refresh(a); aid=a.id
                    with tenant_scope(B):
                        async with AsyncSessionLocal() as db:
                            b=Account(phone='+2001',session_file='b',status='connected')
                            db.add(b); await db.commit(); await db.refresh(b); bid=b.id
                    with tenant_scope(A):
                        async with AsyncSessionLocal() as db:
                            assert await db.get(Account,bid) is None
                            assert (await db.execute(select(Account))).scalars().all()[0].id == aid
                            result=await db.execute(update(Account).where(Account.id==bid).values(status='removed'))
                            assert result.rowcount == 0
                            result=await db.execute(delete(Account).where(Account.id==bid))
                            assert result.rowcount == 0
                            await db.commit()
                    with system_scope():
                        async with AsyncSessionLocal() as db:
                            owners={{r.user_id for r in (await db.execute(select(Account))).scalars().all()}}
                            assert owners == {{A,B}}
                asyncio.run(main())
            ''')
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_phone_unique_is_scoped_to_tenant(self):
        with tempfile.TemporaryDirectory(prefix='mtm_tenant_phone_') as td:
            env = migrated_env(Path(td) / 'phone.db')
            code = textwrap.dedent(f'''\
                import asyncio
                from sqlalchemy.exc import IntegrityError
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.tenant import tenant_scope
                A={A!r}; B={B!r}; PHONE='+84999999999'

                async def add(uid):
                    with tenant_scope(uid):
                        async with AsyncSessionLocal() as db:
                            db.add(Account(phone=PHONE,session_file='x',status='connected'))
                            await db.commit()
                async def main():
                    await add(A); await add(B)
                    try: await add(A)
                    except IntegrityError: return
                    raise AssertionError('same tenant duplicate phone was not blocked')
                asyncio.run(main())
            ''')
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_rls_migration_covers_every_tenant_table(self):
        source=(BACKEND/'alembic'/'versions'/'e9a1b2c3d4e5_supabase_rls_tenant_policies.py').read_text(encoding='utf-8')
        self.assertIn("auth.uid()", source)
        self.assertIn("ENABLE ROW LEVEL SECURITY", source)
        self.assertIn("FORCE ROW LEVEL SECURITY", source)
        self.assertIn("REVOKE ALL ON TABLE", source)
        sys.path.insert(0, str(BACKEND))
        from app.models import TENANT_TABLE_NAMES
        ns={}
        exec(compile(source, '<rls-migration>', 'exec'), ns)
        self.assertEqual(set(ns['TENANT_TABLES']), set(TENANT_TABLE_NAMES))

    def test_runtime_settings_are_tenant_scoped(self):
        with tempfile.TemporaryDirectory(prefix='mtm_tenant_runtime_') as td:
            env=migrated_env(Path(td)/'runtime.db')
            code=textwrap.dedent(f'''\
                import asyncio
                from app.db import AsyncSessionLocal
                from app.models import AppSetting
                from app.runtime_settings import bulk_limits, auto_reconnect_enabled
                from app.tenant import tenant_scope
                A={A!r}; B={B!r}
                async def seed(uid, lo, hi, conc, auto):
                    with tenant_scope(uid):
                        async with AsyncSessionLocal() as db:
                            for k,v in [('rate_min',lo),('rate_max',hi),('concurrency',conc),('auto_reconnect',auto)]:
                                db.add(AppSetting(user_id=uid,key=f'user:{{uid}}:{{k}}',value=str(v)))
                            await db.commit()
                async def main():
                    await seed(A,0.1,0.2,3,'false'); await seed(B,1.0,2.0,7,'true')
                    assert await bulk_limits(A) == (0.1,0.2,3)
                    assert await bulk_limits(B) == (1.0,2.0,7)
                    assert await auto_reconnect_enabled(A) is False
                    assert await auto_reconnect_enabled(B) is True
                asyncio.run(main())
            ''')
            subprocess.run([PYTHON,'-c',code],cwd=BACKEND,env=env,check=True)


if __name__ == '__main__':
    unittest.main()
