from __future__ import annotations

import ast
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


class AuditLifecycleTests(unittest.TestCase):
    def test_auth_audit_never_receives_otp_or_password(self):
        code = textwrap.dedent("""
            import asyncio
            from app.routers import accounts
            from app.schemas import SendCodeIn

            async def main():
                captured=[]
                async def fake_send_code(phone): return 'server-hash'
                async def fake_audit(action, account_id=None, detail=None):
                    captured.append((action, account_id, detail or {}))
                accounts.manager.send_code=fake_send_code
                accounts.log_audit=fake_audit
                body=SendCodeIn(phone='+15551234567')
                result=await accounts.send_code(body)
                assert result['ok'] is True
                assert captured == [('auth:code_sent', None, {'phone_suffix':'4567'})]
                serialized=repr(captured).lower()
                assert 'server-hash' not in serialized
                assert 'password' not in serialized
                assert 'otp' not in serialized
            asyncio.run(main())
        """)
        subprocess.run([PYTHON, '-c', code], cwd=BACKEND, check=True)

    def test_gone_history_delete_is_audited(self):
        with tempfile.TemporaryDirectory(prefix='mtm_audit_gone_') as td:
            db_path = Path(td) / 'audit.db'
            env = os.environ.copy()
            env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': ''})
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from sqlalchemy import select
                from app.db import AsyncSessionLocal
                from app.models import AuditLog, GoneAccount
                from app.routers.accounts import clear_gone_accounts

                async def main():
                    async with AsyncSessionLocal() as db:
                        db.add_all([
                            GoneAccount(phone='+1001', reason='removed'),
                            GoneAccount(phone='+1002', reason='banned'),
                        ])
                        await db.commit()
                        result=await clear_gone_accounts(db)
                        assert result['ok'] is True
                        assert (await db.execute(select(GoneAccount))).scalars().all() == []
                        audits=(await db.execute(select(AuditLog).where(AuditLog.action=='gone:cleared'))).scalars().all()
                        assert len(audits)==1
                        assert audits[0].detail == {'removed': 2}
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_security_message_state_changes_are_audited(self):
        with tempfile.TemporaryDirectory(prefix='mtm_audit_security_') as td:
            db_path = Path(td) / 'audit-security.db'
            env = os.environ.copy()
            env.update({'DB_URL': f'sqlite+aiosqlite:///{db_path}', 'DATABASE_URL': ''})
            subprocess.run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            code = textwrap.dedent("""
                import asyncio
                from sqlalchemy import select
                from app.db import AsyncSessionLocal
                from app.models import Account, AuditLog, SecurityMessage
                from app.routers.security import mark_read, mark_all_read

                async def main():
                    async with AsyncSessionLocal() as db:
                        acc=Account(phone='+2001',session_file='s',status='connected')
                        db.add(acc); await db.flush()
                        m1=SecurityMessage(account_id=acc.id,tg_msg_id=9001,message_text='x',type='login',is_read=False)
                        m2=SecurityMessage(account_id=acc.id,tg_msg_id=9002,message_text='y',type='login',is_read=False)
                        db.add_all([m1,m2]); await db.commit(); await db.refresh(m1); await db.refresh(m2)
                        await mark_read(m1.id, db)
                        await mark_all_read(acc.id, db)
                    async with AsyncSessionLocal() as db:
                        rows=(await db.execute(select(AuditLog).where(AuditLog.action.in_(['security:message_read','security:messages_mark_all_read'])).order_by(AuditLog.id))).scalars().all()
                        assert [r.action for r in rows]==['security:message_read','security:messages_mark_all_read']
                        assert rows[0].detail=={'security_record_id':m1.id}
                        assert rows[1].detail['updated'] >= 1
                        assert all('message_text' not in (r.detail or {}) for r in rows)
                asyncio.run(main())
            """)
            subprocess.run([PYTHON, '-c', code], cwd=BACKEND, env=env, check=True)

    def test_security_backfill_audit_uses_counts_only(self):
        code = textwrap.dedent("""
            import asyncio
            from app.routers import security

            async def main():
                captured=[]
                client=object()
                security.manager.get=lambda aid: client
                async def fake_backfill(aid, cli, limit=50):
                    assert cli is client and aid==7 and limit==200
                    return 3
                async def fake_audit(action, account_id=None, detail=None):
                    captured.append((action,account_id,detail or {}))
                security.manager._backfill_777000=fake_backfill
                security.log_audit=fake_audit
                result=await security.backfill(7,999)
                assert result=={'ok':True,'added':3}
                assert captured==[('security:backfill',7,{'added':3,'limit':200})]
                serialized=repr(captured).lower()
                assert 'message_text' not in serialized and 'password' not in serialized and 'token' not in serialized
            asyncio.run(main())
        """)
        subprocess.run([PYTHON, '-c', code], cwd=BACKEND, check=True)

    def test_mutating_routes_have_audit_or_reviewed_exception(self):
        reviewed = {
            'accounts.py:qr_poll',
            'accounts.py:qr_sign_in_2fa',
            'messaging.py:allowed_reactions',
            'messaging.py:target_check',
            'phone_checks.py:preview_numbers',
            'phone_checks.py:import_numbers',
        }
        unaudited = set()
        for path in sorted((BACKEND / 'app' / 'routers').glob('*.py')):
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source)
            lines = source.splitlines()
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                mutating_route = False
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in {'post', 'put', 'delete', 'patch'}
                    ):
                        mutating_route = True
                if not mutating_route:
                    continue
                body = '\n'.join(lines[node.lineno - 1:getattr(node, 'end_lineno', node.lineno)])
                if not ('log_audit(' in body or 'AuditLog(' in body or 'bulk_stream(' in body):
                    unaudited.add(f'{path.name}:{node.name}')

        self.assertEqual(unaudited, reviewed)
        account_source = (BACKEND / 'app' / 'routers' / 'accounts.py').read_text(encoding='utf-8')
        self.assertGreaterEqual(account_source.count('_finalize_qr('), 3)



if __name__ == '__main__':
    unittest.main()
