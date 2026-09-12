from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.functions.account import (
    UpdateProfileRequest, UpdateUsernameRequest, CheckUsernameRequest,
)
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest, GetUserPhotosRequest
from telethon.errors import UsernameOccupiedError, UsernameInvalidError, FloodWaitError
import io
import tempfile
import os

from ..db import get_db
from ..models import Account
from ..schemas import AccountOut, ProfileUpdateIn, UsernameUpdateIn, UsernameCheckOut
from ..tg_manager import manager
from ..utils import read_upload_limited, friendly_error
from ..audit import log_audit
from .accounts import _account_to_out

router = APIRouter(prefix="/api/accounts/{account_id}/profile", tags=["profile"])

MAX_PROFILE_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_PROFILE_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}



def _client_or_404(account_id: int):
    cli = manager.get(account_id)
    if not cli:
        raise HTTPException(409, "Tài khoản chưa kết nối")
    return cli


@router.put("", response_model=AccountOut)
async def update_profile(account_id: int, body: ProfileUpdateIn, db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    cli = _client_or_404(account_id)
    try:
        kw = {}
        if body.first_name is not None:
            kw["first_name"] = body.first_name
        if body.last_name is not None:
            kw["last_name"] = body.last_name
        if body.bio is not None:
            if len(body.bio) > 70:
                raise HTTPException(400, "Tiểu sử tối đa 70 ký tự")
            kw["about"] = body.bio
        if kw:
            async with manager.account_operation(account_id, "profile_update"):
                await cli(UpdateProfileRequest(**kw))
        if body.first_name is not None: acc.first_name = body.first_name
        if body.last_name is not None: acc.last_name = body.last_name
        if body.bio is not None: acc.bio = body.bio
        await db.commit()
        await db.refresh(acc)
        await log_audit("profile:update", account_id, {"fields": list(kw.keys())})
    except FloodWaitError as e:
        raise HTTPException(429, f"FloodWait: chờ {e.seconds} giây")
    except Exception as e:
        raise HTTPException(400, friendly_error(e))
    return await _account_to_out(acc, db)


@router.get("/check_username", response_model=UsernameCheckOut)
async def check_username(account_id: int, username: str):
    cli = _client_or_404(account_id)
    if not username:
        return UsernameCheckOut(available=False, reason="empty")
    try:
        ok = await cli(CheckUsernameRequest(username=username))
        return UsernameCheckOut(available=bool(ok))
    except UsernameInvalidError:
        return UsernameCheckOut(available=False, reason="invalid")
    except UsernameOccupiedError:
        return UsernameCheckOut(available=False, reason="occupied")
    except Exception as e:
        return UsernameCheckOut(available=False, reason=friendly_error(e)[:80])


@router.put("/username", response_model=AccountOut)
async def update_username(account_id: int, body: UsernameUpdateIn, db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    cli = _client_or_404(account_id)
    try:
        async with manager.account_operation(account_id, "profile_username"):
            await cli(UpdateUsernameRequest(username=body.username))
        acc.username = body.username
        await db.commit()
        await db.refresh(acc)
        await log_audit("profile:username", account_id, {"username": body.username})
    except UsernameOccupiedError:
        raise HTTPException(409, "Tên người dùng đã được sử dụng")
    except UsernameInvalidError:
        raise HTTPException(400, "Tên người dùng không hợp lệ")
    except FloodWaitError as e:
        raise HTTPException(429, f"FloodWait: chờ {e.seconds} giây")
    except Exception as e:
        raise HTTPException(400, friendly_error(e))
    return await _account_to_out(acc, db)


@router.post("/photo", response_model=AccountOut)
async def upload_photo(account_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    cli = _client_or_404(account_id)
    suffix = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    if suffix not in ALLOWED_PROFILE_PHOTO_EXTS:
        raise HTTPException(400, "Ảnh hồ sơ phải là JPG, PNG hoặc WEBP")
    try:
        data = await read_upload_limited(file, MAX_PROFILE_PHOTO_BYTES)
    except ValueError as exc:
        raise HTTPException(413, str(exc))
    if not data:
        raise HTTPException(400, "Ảnh trống")
    # Telethon needs a file path or BinaryIO with a name
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        async with manager.account_operation(account_id, "profile_photo"):
            uploaded = await cli.upload_file(tmp_path)
            await cli(UploadProfilePhotoRequest(file=uploaded))
        await log_audit("profile:photo", account_id, {"file_type": suffix})
    except FloodWaitError as e:
        raise HTTPException(429, f"FloodWait: chờ {e.seconds} giây")
    except Exception as e:
        raise HTTPException(400, friendly_error(e))
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass
    return await _account_to_out(acc, db)


@router.get("/photo_url")
async def get_photo_url(account_id: int):
    """Return current profile photo as base64 data url (small)."""
    cli = _client_or_404(account_id)
    try:
        me = await cli.get_me()
        buf = io.BytesIO()
        downloaded = await cli.download_profile_photo(me, file=buf)
        if not downloaded:
            return {"data_url": None}
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"data_url": f"data:image/jpeg;base64,{b64}"}
    except Exception:
        return {"data_url": None}
