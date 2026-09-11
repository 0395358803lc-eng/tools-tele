"""Encrypted SQL store for sensitive runtime values, with legacy file migration."""
from __future__ import annotations
import asyncio, json, os, re
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from .time_utils import utcnow
from .config import settings
from .db import AsyncSessionLocal
from .models import EncryptedSecret

_lock = asyncio.Lock()

def _path() -> Path:
    return settings.sessions_path / "twofa.enc"
def _legacy_path() -> Path:
    return settings.sessions_path / "twofa.json"
def _norm_phone(phone: str) -> str:
    p=(phone or '').strip(); digits=re.sub(r'[^0-9]','',p); return f'+{digits}' if digits else p
def _cipher() -> Fernet:
    raw=(settings.SECRETS_ENCRYPTION_KEY or '').strip()
    if not raw: raise RuntimeError('Cần SECRETS_ENCRYPTION_KEY để mã hóa dữ liệu bí mật')
    try: return Fernet(raw.encode('ascii'))
    except Exception as exc: raise RuntimeError('SECRETS_ENCRYPTION_KEY không phải khóa Fernet hợp lệ') from exc

def encrypt_value(value: str) -> str:
    return _cipher().encrypt(value.encode('utf-8')).decode('ascii')
def decrypt_value(token: str) -> str:
    try: return _cipher().decrypt(token.encode('ascii')).decode('utf-8')
    except InvalidToken as exc: raise RuntimeError('Không thể giải mã dữ liệu bí mật bằng khóa đã cấu hình') from exc

def _decode_legacy(blob: bytes) -> dict[str,str]:
    plain=_cipher().decrypt(blob); data=json.loads(plain.decode('utf-8') or '{}')
    return {str(k):str(v) for k,v in data.items() if v} if isinstance(data,dict) else {}

async def save_2fa(phone: str, password: str):
    if not phone or not password: return
    key='twofa:'+_norm_phone(phone)
    async with _lock:
        async with AsyncSessionLocal() as db:
            row=await db.get(EncryptedSecret,key)
            if row:
                row.ciphertext=encrypt_value(password); row.updated_at=utcnow()
            else:
                db.add(EncryptedSecret(key=key,ciphertext=encrypt_value(password),updated_at=utcnow()))
            await db.commit()

async def get_2fa(phone: str) -> str | None:
    key='twofa:'+_norm_phone(phone)
    async with AsyncSessionLocal() as db:
        row=await db.get(EncryptedSecret,key)
        return decrypt_value(row.ciphertext) if row else None

async def known_passwords() -> list[str]:
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(EncryptedSecret).where(EncryptedSecret.key.like('twofa:%')))).scalars().all()
        return list(dict.fromkeys(decrypt_value(r.ciphertext) for r in rows if r.ciphertext))

async def count() -> int:
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(EncryptedSecret.key).where(EncryptedSecret.key.like('twofa:%')))).all()
        return len(rows)

async def migrate_legacy_to_db() -> int:
    """One-time import of twofa.enc/twofa.json into encrypted SQL rows."""
    async with _lock:
        data: dict[str,str] = {}
        enc=_path(); plain=_legacy_path()
        if enc.exists():
            data.update(_decode_legacy(enc.read_bytes()))
        if plain.exists():
            raw=json.loads(plain.read_text(encoding='utf-8') or '{}')
            if isinstance(raw,dict): data.update({str(k):str(v) for k,v in raw.items() if v})
        if not data: return 0
        async with AsyncSessionLocal() as db:
            for phone,password in data.items():
                key='twofa:'+_norm_phone(phone); row=await db.get(EncryptedSecret,key)
                if not row: db.add(EncryptedSecret(key=key,ciphertext=encrypt_value(password),updated_at=utcnow()))
            await db.commit()
        for p in (enc,plain):
            try:
                if p.exists(): p.unlink()
            except OSError: pass
        return len(data)
