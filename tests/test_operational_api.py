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


class OperationalApiTests(unittest.TestCase):
    def _env(self, db_path: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': ''})
        return env

    def test_account_output_does_not_echo_raw_persisted_error(self):
        with tempfile.TemporaryDirectory(prefix='mtm_account_output_') as td:
            db_path = Path(td) / 'accounts.db'
            env = self._env(db_path)
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app.routers.accounts import _account_to_out

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        acc = Account(
                            phone='safe-output', session_file='s', status='network_error',
                            last_error_type='ValueError',
                            last_error='password=never-echo /private/server/path',
                        )
                        db.add(acc); await db.commit(); await db.refresh(acc)
                        out = await _account_to_out(acc, db)
                        assert out.last_error_type == 'ValueError'
                        assert 'never-echo' not in (out.last_error or '')
                        assert '/private/server/path' not in (out.last_error or '')
                        assert 'thao tác thất bại' in (out.last_error or '')

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_target_check_history_has_counts_and_account_identity(self):
        with tempfile.TemporaryDirectory(prefix='mtm_target_history_') as td:
            db_path = Path(td) / 'target.db'
            env = self._env(db_path)
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from app.db import AsyncSessionLocal
                from app.models import Account, TargetCheck, TargetCheckResult
                from app.routers.messaging import target_check_history, target_check_detail

                from app.tenant import set_tenant_id
                set_tenant_id('00000000-0000-4000-8000-000000000001')

                async def main():
                    async with AsyncSessionLocal() as db:
                        a1=Account(phone='+1001',first_name='Alpha',last_name='One',username='alpha',session_file='a1',status='connected')
                        a2=Account(phone='+1002',first_name='Beta',last_name='Two',username='beta',session_file='a2',status='connected')
                        db.add_all([a1,a2]); await db.flush()
                        check=TargetCheck(id='check-test',target='@example',peer={'kind':'bot','id':9000000001},total=2)
                        db.add(check)
                        db.add_all([
                            TargetCheckResult(target_check_id='check-test',account_id=a1.id,status='present',detail='already used'),
                            TargetCheckResult(target_check_id='check-test',account_id=a2.id,status='absent',detail='not used'),
                        ])
                        await db.commit()
                        history=await target_check_history(50,db)
                        assert len(history)==1
                        assert history[0]['counts']=={'present':1,'absent':1,'skipped':0,'failed':0}
                        detail=await target_check_detail('check-test',db)
                        assert detail['counts']==history[0]['counts']
                        assert detail['results'][0]['phone']=='+1001'
                        assert detail['results'][0]['name']=='Alpha One'
                        assert detail['results'][1]['username']=='beta'

                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
