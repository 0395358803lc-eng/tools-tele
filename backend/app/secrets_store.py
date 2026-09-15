"""Encrypted tenant-scoped SQL store for sensitive runtime values."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from .config import settings
from .db import AsyncSessionLocal
from .models import EncryptedSecret
from .tenant import current_tenant_id, tenant_scope
from .time_utils import utcnow

_lock = asyncio.Lock()


def _path() -> Path:
    return settings.sessions_path / "twofa.enc"


def _legacy_path() -> Path:
    return settings.sessions_path / "twofa.json"


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"[^0-9]", "", (phone or "").strip())
    return f"+{digits}" if digits else (phone or "").strip()


def _key_path() -> Path:
    return settings.sessions_path / ".encryption.key"

def _load_or_create_key() -> str:
    path = _key_path()
    if path.exists():
        raw = path.read_text(encoding="ascii").strip()
    else:
        raw = Fernet.generate_key().decode("ascii")
        path.write_text(raw, encoding="ascii")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    try:
        Fernet(raw.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("Internal encryption key is invalid") from exc
    return raw


def encryption_ready() -> bool:
    try:
        _load_or_create_key()
        return True
    except Exception:
        return False


def _cipher() -> Fernet:
    return Fernet(_load_or_create_key().encode("ascii"))


def encrypt_value(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Không thể giải mã dữ liệu bí mật bằng khóa hiện tại") from exc


def _tenant(user_id: str | None = None) -> str:
    uid = str(user_id or current_tenant_id() or "").strip()
    if not uid:
        raise RuntimeError("Thiếu tenant context cho secret")
    return uid


def _storage_key(name: str, user_id: str | None = None) -> tuple[str, str]:
    uid = _tenant(user_id)
    return uid, f"user:{uid}:{name}"

async def save_named_secret(name: str, value: str, user_id: str | None = None) -> None:
    if not name or not value:
        raise ValueError("Secret key/value must not be empty")
    uid, key = _storage_key(name, user_id)
    async with _lock:
        with tenant_scope(uid):
            async with AsyncSessionLocal() as db:
                row = await db.get(EncryptedSecret, key)
                cipher = encrypt_value(value)
                if row:
                    row.ciphertext = cipher
                    row.updated_at = utcnow()
                else:
                    db.add(EncryptedSecret(
                        user_id=uid, key=key, ciphertext=cipher, updated_at=utcnow()
                    ))
                await db.commit()


async def get_named_secret(name: str, user_id: str | None = None) -> str | None:
    uid, key = _storage_key(name, user_id)
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            row = await db.get(EncryptedSecret, key)
            return decrypt_value(row.ciphertext) if row else None

async def save_telegram_api_config(
    api_id: int, api_hash: str, user_id: str | None = None
) -> None:
    uid = _tenant(user_id)
    await save_named_secret("telegram:api_id", str(int(api_id)), uid)
    await save_named_secret("telegram:api_hash", api_hash.strip(), uid)


async def get_telegram_api_config(
    user_id: str | None = None,
) -> tuple[int, str] | None:
    uid = _tenant(user_id)
    api_id = await get_named_secret("telegram:api_id", uid)
    api_hash = await get_named_secret("telegram:api_hash", uid)
    if not api_id or not api_hash:
        return None
    return int(api_id), api_hash


async def load_telegram_api_config(user_id: str | None = None) -> bool:
    cfg = await get_telegram_api_config(user_id)
    return bool(cfg)


async def save_2fa(phone: str, password: str, user_id: str | None = None) -> None:
    if not phone or not password:
        return
    await save_named_secret("twofa:" + _norm_phone(phone), password, user_id)


async def get_2fa(phone: str, user_id: str | None = None) -> str | None:
    return await get_named_secret("twofa:" + _norm_phone(phone), user_id)

async def known_passwords(user_id: str | None = None) -> list[str]:
    uid = _tenant(user_id)
    prefix = f"user:{uid}:twofa:%"
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(EncryptedSecret).where(EncryptedSecret.key.like(prefix))
            )).scalars().all()
            return list(dict.fromkeys(
                decrypt_value(row.ciphertext) for row in rows if row.ciphertext
            ))


async def count(user_id: str | None = None) -> int:
    uid = _tenant(user_id)
    prefix = f"user:{uid}:twofa:%"
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(EncryptedSecret.key).where(EncryptedSecret.key.like(prefix))
            )).all()
            return len(rows)


def _decode_legacy(blob: bytes) -> dict[str, str]:
    plain = _cipher().decrypt(blob)
    data = json.loads(plain.decode("utf-8") or "{}")
    return {str(k): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}

async def migrate_legacy_to_db() -> int:
    """Import legacy 2FA files into the configured legacy ADMIN tenant once."""
    owner = (settings.LEGACY_OWNER_USER_ID or "").strip()
    if not owner:
        return 0
    async with _lock:
        data: dict[str, str] = {}
        enc, plain = _path(), _legacy_path()
        if enc.exists():
            data.update(_decode_legacy(enc.read_bytes()))
        if plain.exists():
            raw = json.loads(plain.read_text(encoding="utf-8") or "{}")
            if isinstance(raw, dict):
                data.update({str(k): str(v) for k, v in raw.items() if v})
        if not data:
            return 0
        for phone, password in data.items():
            await save_named_secret("twofa:" + _norm_phone(phone), password, owner)
        for path in (enc, plain):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        return len(data)
