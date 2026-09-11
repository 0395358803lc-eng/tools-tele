from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.errors import UsernameNotModifiedError
import tempfile, os

from ..db import get_db, AsyncSessionLocal
from ..models import Account
from ..schemas import BulkProfileIn
from ..tg_manager import manager
from ..utils import bulk_stream, read_upload_limited

router = APIRouter(prefix="/api/bulk", tags=["bulk"])

MAX_BULK_PHOTO_BYTES = 10 * 1024 * 1024
MAX_BULK_PHOTO_FILES = 200
ALLOWED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}



@router.post("/profile")
async def bulk_profile(body: BulkProfileIn, db: AsyncSession = Depends(get_db)):
    """Streaming bulk profile edit (live progress).
       - same first_name/last_name/bio for everyone (with optional number suffix), OR
       - per_account: { account_id: {first_name, last_name, bio} } (from CSV import)
    """
    res = await db.execute(select(Account).where(Account.id.in_(body.account_ids), Account.deleted_at.is_(None)))
    by_id = {a.id: a for a in res.scalars().all()}

    # Pre-compute the field changes per account in selection order so the parallel
    # workers stay deterministic (e.g. "Family 1", "Family 2" numbering).
    plan: dict[int, dict] = {}
    uname_plan: dict[int, str] = {}   # account_id -> desired @username
    n = body.start_number
    for aid in body.account_ids:
        acc = by_id.get(aid)
        if not acc:
            continue
        per = body.per_account.get(str(aid)) if body.per_account else None
        fn = (per or {}).get("first_name") if per else body.first_name
        ln = (per or {}).get("last_name") if per else body.last_name
        bio = (per or {}).get("bio") if per else body.bio
        # Username: can come from CSV (per-account) OR simple mode with append_number.
        # Telegram usernames are globally unique, so simple mode only works with
        # append_number to generate unique usernames (e.g. "myuser1", "myuser2").
        uname = (per or {}).get("username") if per else body.username
        kw: dict = {}
        used_number = False
        if fn is not None:
            if body.append_number and not per:
                fn = f"{fn} {n}"; used_number = True
            kw["first_name"] = fn
        if ln is not None:
            if body.append_number and not per:
                ln = f"{ln} {n}"; used_number = True
            kw["last_name"] = ln
        if bio is not None:
            kw["about"] = bio
        plan[aid] = kw
        if uname:
            cleaned = uname.strip().lstrip("@")
            if cleaned:
                # In simple mode with append_number, append the number to username
                if body.append_number and not per:
                    cleaned = f"{cleaned}{n}"
                    used_number = True
                uname_plan[aid] = cleaned
        if used_number:
            n += 1

    accounts = [
        (a.id, a.phone, (f"{a.first_name or ''} {a.last_name or ''}".strip() or a.phone))
        for a in (by_id[i] for i in body.account_ids if i in by_id)
    ]

    async def _do(cli, aid):
        kw = plan.get(aid) or {}
        uname = uname_plan.get(aid)
        if not kw and not uname:
            return "ok", "không có nội dung cần thay đổi"
        detail: list[str] = []

        # 1) name / bio (single UpdateProfile call)
        if kw:
            if kw.get("about") is not None and len(kw["about"]) > 70:
                raise ValueError("Tiểu sử tối đa 70 ký tự")
            await cli(UpdateProfileRequest(**kw))

        # 2) username (separate call; may fail per-account — taken/invalid surface
        #    as a failed row via friendly_error, "unchanged" counts as success).
        username_set = None
        if uname:
            try:
                await cli(UpdateUsernameRequest(username=uname))
                username_set = uname
                detail.append(f"@{uname}")
            except UsernameNotModifiedError:
                username_set = uname
                detail.append(f"@{uname} (unchanged)")

        # persist whatever actually changed
        if kw or username_set:
            async with AsyncSessionLocal() as s:
                acc = await s.get(Account, aid)
                if acc:
                    if "first_name" in kw: acc.first_name = kw["first_name"]
                    if "last_name" in kw: acc.last_name = kw["last_name"]
                    if "about" in kw: acc.bio = kw["about"]
                    if username_set is not None: acc.username = username_set
                    await s.commit()
        return "ok", ", ".join(detail)

    return StreamingResponse(bulk_stream(accounts, _do, job_type="bulk_profile"), media_type="application/x-ndjson")


@router.post("/photo")
async def bulk_photo(
    account_ids: str = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Streaming bulk profile photo (live progress). One photo per account in order.
    - If len(files) >= len(accounts): first N files used, rest ignored.
    - If len(files) <  len(accounts): only first len(files) accounts updated, others skipped.
    """
    ids = [int(x) for x in account_ids.split(",") if x.strip()]
    if len(files) > MAX_BULK_PHOTO_FILES:
        raise HTTPException(413, f"Tối đa {MAX_BULK_PHOTO_FILES} ảnh cho mỗi yêu cầu")
    res = await db.execute(select(Account).where(Account.id.in_(ids), Account.deleted_at.is_(None)))
    by_id = {a.id: a for a in res.scalars().all()}
    ordered = [by_id[i] for i in ids if i in by_id]

    # write all uploads to disk first; map account-index -> temp path
    tmp_paths: list[str] = []
    for f in files:
        suffix = os.path.splitext(f.filename or "photo.jpg")[1].lower() or ".jpg"
        if suffix not in ALLOWED_PHOTO_EXTS:
            raise HTTPException(400, f"Định dạng ảnh không được hỗ trợ: {suffix}")
        try:
            data = await read_upload_limited(f, MAX_BULK_PHOTO_BYTES)
        except ValueError as exc:
            raise HTTPException(413, str(exc))
        if not data:
            raise HTTPException(400, "Ảnh trống")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data); tmp_paths.append(tmp.name)

    path_by_id: dict[int, str | None] = {}
    for idx, acc in enumerate(ordered):
        path_by_id[acc.id] = tmp_paths[idx] if idx < len(tmp_paths) else None

    accounts = [
        (a.id, a.phone, (f"{a.first_name or ''} {a.last_name or ''}".strip() or a.phone))
        for a in ordered
    ]

    async def _do(cli, aid):
        path = path_by_id.get(aid)
        if not path:
            return "skipped", "không có ảnh cho tài khoản này"
        up = await cli.upload_file(path)
        await cli(UploadProfilePhotoRequest(file=up))
        return "ok", ""

    async def _gen():
        try:
            async for line in bulk_stream(accounts, _do, job_type="bulk_photo"):
                yield line
        finally:
            for p in tmp_paths:
                try: os.unlink(p)
                except Exception: pass

    return StreamingResponse(_gen(), media_type="application/x-ndjson")
