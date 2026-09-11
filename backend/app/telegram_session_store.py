from __future__ import annotations
from datetime import datetime
from sqlalchemy import select, delete
from telethon.sessions import StringSession
from .time_utils import utcnow
from .db import AsyncSessionLocal
from .models import TelegramSession
from .secrets_store import encrypt_value, decrypt_value

async def load(account_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        res=await db.execute(select(TelegramSession).where(TelegramSession.account_id==account_id, TelegramSession.is_primary.is_(True)).order_by(TelegramSession.id.desc()))
        row=res.scalars().first()
        if not row or not row.session_ciphertext: return None
        return decrypt_value(row.session_ciphertext)

async def save(account_id: int, client, session_file: str = '') -> None:
    raw=StringSession.save(client.session)
    if not raw: return
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(TelegramSession).where(TelegramSession.account_id==account_id))).scalars().all()
        row=next((r for r in rows if r.is_primary), None)
        for other in rows:
            if other is not row: other.is_primary=False
        if row:
            row.session_file=session_file or row.session_file
            row.session_ciphertext=encrypt_value(raw); row.status='active'; row.last_connected_at=utcnow(); row.last_error=None
        else:
            db.add(TelegramSession(account_id=account_id,session_file=session_file or f'account_{account_id}',status='active',is_primary=True,last_connected_at=utcnow(),session_ciphertext=encrypt_value(raw)))
        await db.commit()

async def clear(account_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TelegramSession).where(TelegramSession.account_id==account_id)); await db.commit()
