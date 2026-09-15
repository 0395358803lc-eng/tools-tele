from __future__ import annotations

from sqlalchemy import delete, select
from telethon.sessions import StringSession

from .db import AsyncSessionLocal
from .models import Account, TelegramSession
from .secrets_store import decrypt_value, encrypt_value
from .tenant import current_tenant_id, system_scope, tenant_scope
from .time_utils import utcnow


async def _owner(account_id: int, user_id: str | None = None) -> str:
    if user_id:
        return str(user_id)
    current = current_tenant_id()
    if current:
        return current
    with system_scope():
        async with AsyncSessionLocal() as db:
            account = await db.get(Account, account_id)
            if not account:
                raise RuntimeError("Không tìm thấy chủ sở hữu Telegram session")
            return account.user_id


async def load(account_id: int, user_id: str | None = None) -> str | None:
    uid = await _owner(account_id, user_id)
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(TelegramSession).where(
                    TelegramSession.account_id == account_id,
                    TelegramSession.is_primary.is_(True),
                ).order_by(TelegramSession.id.desc())
            )).scalars().first()
            if not row or not row.session_ciphertext:
                return None
            return decrypt_value(row.session_ciphertext)

async def save(
    account_id: int,
    client,
    session_file: str = "",
    user_id: str | None = None,
) -> None:
    raw = StringSession.save(client.session)
    if not raw:
        return
    uid = await _owner(account_id, user_id)
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(TelegramSession).where(TelegramSession.account_id == account_id)
            )).scalars().all()
            row = next((item for item in rows if item.is_primary), None)
            for other in rows:
                if other is not row:
                    other.is_primary = False
            if row:
                row.session_file = session_file or row.session_file
                row.session_ciphertext = encrypt_value(raw)
                row.status = "active"
                row.last_connected_at = utcnow()
                row.last_error = None
            else:
                db.add(TelegramSession(
                    user_id=uid,
                    account_id=account_id,
                    session_file=session_file or f"account_{account_id}",
                    status="active",
                    is_primary=True,
                    last_connected_at=utcnow(),
                    session_ciphertext=encrypt_value(raw),
                ))
            await db.commit()

async def clear(account_id: int, user_id: str | None = None) -> None:
    uid = await _owner(account_id, user_id)
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(TelegramSession).where(TelegramSession.account_id == account_id)
            )
            await db.commit()
