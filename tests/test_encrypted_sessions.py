from __future__ import annotations
import os, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'backend'
WORKSPACE=ROOT.parents[1]
VENV=WORKSPACE/'.venv'/'bin'/'python'
PYTHON=str(VENV if VENV.exists() else Path(sys.executable))

class EncryptedSessionTests(unittest.TestCase):
    def test_session_and_twofa_are_encrypted_in_sql(self):
        with tempfile.TemporaryDirectory(prefix='mtm_secret_db_') as td:
            db=Path(td)/'secret.db'; key=Fernet.generate_key().decode()
            env=os.environ.copy(); env.update({'DB_URL':f'sqlite+aiosqlite:///{db}','DATABASE_URL':'','SECRETS_ENCRYPTION_KEY':key,'SESSIONS_DIR':str(Path(td)/'sessions')})
            subprocess.run([PYTHON,'-m','alembic','upgrade','head'],cwd=BACKEND,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            code=textwrap.dedent('''
                import asyncio
                from sqlalchemy import select
                from telethon.sessions import MemorySession, StringSession
                from telethon.crypto import AuthKey
                from app.db import AsyncSessionLocal
                from app.models import Account, TelegramSession, EncryptedSecret
                from app import telegram_session_store, secrets_store

                class Client:
                    pass

                async def main():
                    async with AsyncSessionLocal() as db:
                        a=Account(phone='+10000000031',session_file='acc_test',status='connected')
                        db.add(a); await db.commit(); await db.refresh(a); aid=a.id
                    sess=MemorySession(); sess.set_dc(2,'149.154.167.50',443); sess.auth_key=AuthKey(b'x'*256)
                    c=Client(); c.session=sess
                    plain=StringSession.save(sess)
                    await telegram_session_store.save(aid,c,'acc_test')
                    loaded=await telegram_session_store.load(aid)
                    assert loaded==plain
                    await secrets_store.save_2fa('+10000000031','dummy-password-test')
                    assert await secrets_store.get_2fa('+10000000031')=='dummy-password-test'
                    async with AsyncSessionLocal() as db:
                        ts=(await db.execute(select(TelegramSession))).scalar_one()
                        sec=(await db.execute(select(EncryptedSecret))).scalar_one()
                        assert plain not in ts.session_ciphertext
                        assert 'dummy-password-test' not in sec.ciphertext
                    await telegram_session_store.clear(aid)
                    async with AsyncSessionLocal() as db:
                        assert (await db.execute(select(TelegramSession))).scalars().first() is None
                asyncio.run(main())
            ''')
            subprocess.run([PYTHON,'-c',code],cwd=BACKEND,env=env,check=True)

    def test_wrong_encryption_key_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix='mtm_wrong_key_') as td:
            db=Path(td)/'wrong-key.db'
            sessions=Path(td)/'sessions'; sessions.mkdir()
            key1=Fernet.generate_key().decode(); key2=Fernet.generate_key().decode()
            env=os.environ.copy(); env.update({'DB_URL':f'sqlite+aiosqlite:///{db}','DATABASE_URL':'','SECRETS_ENCRYPTION_KEY':key1,'SESSIONS_DIR':str(sessions)})
            subprocess.run([PYTHON,'-m','alembic','upgrade','head'],cwd=BACKEND,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            writer=textwrap.dedent("""
                import asyncio
                from telethon.sessions import MemorySession
                from telethon.crypto import AuthKey
                from app.db import AsyncSessionLocal
                from app.models import Account
                from app import telegram_session_store, secrets_store
                class Client: pass
                async def main():
                    async with AsyncSessionLocal() as db:
                        a=Account(phone='+10000000032',session_file='acc_wrong_key',status='connected')
                        db.add(a); await db.commit(); await db.refresh(a); aid=a.id
                    sess=MemorySession(); sess.set_dc(2,'149.154.167.50',443); sess.auth_key=AuthKey(b'y'*256)
                    c=Client(); c.session=sess
                    await telegram_session_store.save(aid,c,'acc_wrong_key')
                    await secrets_store.save_2fa('+10000000032','key-one-password')
                    print(aid)
                asyncio.run(main())
            """)
            aid=subprocess.check_output([PYTHON,'-c',writer],cwd=BACKEND,env=env,text=True).strip().splitlines()[-1]
            bad_env=env.copy(); bad_env['SECRETS_ENCRYPTION_KEY']=key2
            reader=textwrap.dedent(f"""
                import asyncio
                from app import telegram_session_store, secrets_store
                async def main():
                    failures=0
                    for coro in (
                        telegram_session_store.load({aid}),
                        secrets_store.get_2fa('+10000000032'),
                    ):
                        try:
                            await coro
                        except RuntimeError as exc:
                            assert 'Không thể giải mã' in str(exc)
                            failures += 1
                    assert failures == 2
                asyncio.run(main())
            """)
            subprocess.run([PYTHON,'-c',reader],cwd=BACKEND,env=bad_env,check=True)

if __name__=='__main__': unittest.main()
