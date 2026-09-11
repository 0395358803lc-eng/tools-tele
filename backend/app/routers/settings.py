from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..time_utils import utcnow
from ..db import get_db
from ..models import Account, AppSetting
from ..runtime_settings import apply_runtime, defaults
from ..schemas import SettingsIn, SettingsOut
from ..audit import log_audit

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _read_all(db: AsyncSession) -> dict[str, str]:
    res = await db.execute(select(AppSetting))
    values = defaults()
    values.update({r.key: r.value for r in res.scalars().all()})
    return values


def _to_out(cur: dict[str, str]) -> SettingsOut:
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
    )


@router.get("", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    return _to_out(await _read_all(db))


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsIn, db: AsyncSession = Depends(get_db)):
    if body.rate_min < 0 or body.rate_max < 0:
        raise HTTPException(400, "Độ trễ không được là số âm")
    if body.rate_max < body.rate_min:
        raise HTTPException(400, "Độ trễ tối đa phải lớn hơn hoặc bằng độ trễ tối thiểu")
    if not 1 <= int(body.concurrency) <= 50:
        raise HTTPException(400, "Số tác vụ chạy song song phải từ 1 đến 50")
    if not body.sessions_dir.strip():
        raise HTTPException(400, "Đường dẫn thư mục phiên không được để trống")

    payload = {
        "rate_min": str(body.rate_min),
        "rate_max": str(body.rate_max),
        "concurrency": str(int(body.concurrency)),
        "sessions_dir": body.sessions_dir.strip(),
        "auto_reconnect": "true" if body.auto_reconnect else "false",
        "notification_sound": "true" if body.notification_sound else "false",
    }
    res = await db.execute(select(AppSetting))
    existing = {r.key: r for r in res.scalars().all()}
    for key, value in payload.items():
        if key in existing:
            existing[key].value = value
            existing[key].updated_at = utcnow()
        else:
            db.add(AppSetting(key=key, value=value))
    await db.commit()

    # Live values are applied now. sessions_dir changes apply on restart.
    apply_runtime(payload, include_sessions_dir=False)
    await log_audit("settings:update", detail={
        "rate_min": body.rate_min, "rate_max": body.rate_max,
        "concurrency": int(body.concurrency),
        "auto_reconnect": body.auto_reconnect,
        "notification_sound": body.notification_sound,
    })
    return _to_out(payload)


@router.get("/export")
async def export_json(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Account).where(Account.deleted_at.is_(None)))
    accounts = res.scalars().all()
    out = [{
        "id": a.id, "phone": a.phone, "first_name": a.first_name,
        "last_name": a.last_name, "username": a.username, "bio": a.bio,
        "status": a.status, "has_2fa": a.has_2fa,
        "tg_user_id": a.tg_user_id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in accounts]
    return {"exported_at": utcnow().isoformat(), "count": len(out), "accounts": out}
