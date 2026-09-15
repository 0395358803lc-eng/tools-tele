import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import secrets_store
from ..audit import log_audit
from ..auth import require_auth
from ..db import get_db
from ..models import Account, AppSetting
from ..runtime_settings import defaults
from ..schemas import SettingsIn, SettingsOut
from ..supabase_identity import IdentityUser
from ..time_utils import utcnow

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _key(user_id: str, name: str) -> str:
    return f"user:{user_id}:{name}"


async def _read_all(db: AsyncSession, user_id: str) -> dict[str, str]:
    rows = (await db.execute(select(AppSetting))).scalars().all()
    values = defaults()
    prefix = f"user:{user_id}:"
    for row in rows:
        name = row.key[len(prefix):] if row.key.startswith(prefix) else row.key
        values[name] = row.value
    values["sessions_dir"] = defaults()["sessions_dir"]
    return values


def _to_out(cur: dict[str, str], api_cfg: tuple[int, str] | None) -> SettingsOut:
    try:
        conc = max(1, min(50, int(float(cur.get("concurrency", "8")))))
    except (TypeError, ValueError):
        conc = 8
    return SettingsOut(
        rate_min=float(cur["rate_min"]),
        rate_max=float(cur["rate_max"]),
        concurrency=conc,
        sessions_dir=cur["sessions_dir"],
        auto_reconnect=cur["auto_reconnect"].lower() == "true",
        notification_sound=cur["notification_sound"].lower() == "true",
        tg_api_id=api_cfg[0] if api_cfg else None,
        tg_api_hash_configured=bool(api_cfg and api_cfg[1]),
    )

@router.get("", response_model=SettingsOut)
async def get_settings(
    current: IdentityUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    values = await _read_all(db, current.id)
    api_cfg = await secrets_store.get_telegram_api_config(current.id)
    return _to_out(values, api_cfg)


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsIn,
    current: IdentityUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if body.rate_min < 0 or body.rate_max < 0:
        raise HTTPException(400, "Độ trễ không được là số âm")
    if body.rate_max < body.rate_min:
        raise HTTPException(400, "Độ trễ tối đa phải lớn hơn hoặc bằng độ trễ tối thiểu")
    if not 1 <= int(body.concurrency) <= 50:
        raise HTTPException(400, "Số tác vụ chạy song song phải từ 1 đến 50")
    existing_api = await secrets_store.get_telegram_api_config(current.id)
    api_hash_input = (body.tg_api_hash or "").strip()
    api_config_changed = body.tg_api_id is not None or bool(api_hash_input)
    if api_config_changed:
        api_id = int(body.tg_api_id or (existing_api[0] if existing_api else 0))
        api_hash = api_hash_input or (existing_api[1] if existing_api else "")
        if api_id <= 0:
            raise HTTPException(400, "Telegram App api_id phải là số nguyên dương")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            raise HTTPException(400, "Telegram App api_hash phải gồm đúng 32 ký tự hexadecimal")
        await secrets_store.save_telegram_api_config(api_id, api_hash, current.id)

    payload = {
        "rate_min": str(body.rate_min),
        "rate_max": str(body.rate_max),
        "concurrency": str(int(body.concurrency)),
        "sessions_dir": defaults()["sessions_dir"],
        "auto_reconnect": "true" if body.auto_reconnect else "false",
        "notification_sound": "true" if body.notification_sound else "false",
    }
    rows = (await db.execute(select(AppSetting))).scalars().all()
    existing = {row.key: row for row in rows}
    for name, value in payload.items():
        storage_key = _key(current.id, name)
        row = existing.get(storage_key)
        if row:
            row.value = value
            row.updated_at = utcnow()
        else:
            db.add(AppSetting(
                user_id=current.id,
                key=storage_key,
                value=value,
                updated_at=utcnow(),
            ))
    await db.commit()

    await log_audit("settings:update", detail={
        "rate_min": body.rate_min,
        "rate_max": body.rate_max,
        "concurrency": int(body.concurrency),
        "auto_reconnect": body.auto_reconnect,
        "notification_sound": body.notification_sound,
        "telegram_api_id": api_id if api_config_changed else (existing_api[0] if existing_api else None),
        "telegram_api_hash_changed": bool(api_hash_input),
    })
    api_cfg = await secrets_store.get_telegram_api_config(current.id)
    return _to_out(payload, api_cfg)

@router.get("/export")
async def export_json(
    current: IdentityUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Account).where(Account.deleted_at.is_(None))
    )).scalars().all()
    accounts = [{
        "id": row.id,
        "phone": row.phone,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "username": row.username,
        "bio": row.bio,
        "status": row.status,
        "has_2fa": row.has_2fa,
        "tg_user_id": row.tg_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]
    return {
        "user_id": current.id,
        "exported_at": utcnow().isoformat(),
        "count": len(accounts),
        "accounts": accounts,
    }
