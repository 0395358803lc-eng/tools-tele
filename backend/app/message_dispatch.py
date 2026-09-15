from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .tg_manager import manager

_PHONE_RE = re.compile(r"^\+[\d\s().-]{6,}$")
_NUMERIC_RE = re.compile(r"^-?\d+$")


class TargetResolveError(ValueError):
    pass


def _phone_normalize(value: str) -> str:
    return "+" + "".join(ch for ch in value if ch.isdigit())


def normalize_message_target(raw: str) -> tuple[str, str]:
    """Return (display_target, dedupe_key) without importing unknown contacts."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("Mục tiêu đang trống")
    if len(value) > 255:
        raise ValueError("Mục tiêu dài quá 255 ký tự")

    if _PHONE_RE.fullmatch(value):
        phone = _phone_normalize(value)
        if len(phone) < 8 or len(phone) > 17:
            raise ValueError(f"Số điện thoại không hợp lệ: {value}")
        return phone, f"phone:{phone}"

    if value.lower().startswith("tg://resolve"):
        query = parse_qs(urlparse(value).query)
        domain = (query.get("domain") or [""])[0].strip()
        if not domain:
            raise ValueError("Liên kết tg:// không hợp lệ")
        return f"@{domain}", f"user:{domain.lower()}"

    body = value
    for prefix in ("https://", "http://"):
        if body.lower().startswith(prefix):
            body = body[len(prefix):]
            break
    low = body.lower()
    if low.startswith("t.me/") or low.startswith("telegram.me/"):
        rest = body.split("/", 1)[1]
        if rest.startswith("+") or rest.lower().startswith("joinchat/"):
            raise ValueError("Liên kết mời nhóm/kênh không phải người nhận tin nhắn trực tiếp")
        path = rest.partition("?")[0].strip("/")
        peer = path.split("/")[0].strip()
        if not peer:
            raise ValueError("Liên kết t.me không hợp lệ")
        return f"@{peer}", f"user:{peer.lower()}"

    if value.startswith("@"):
        peer = value[1:].strip()
        if not peer:
            raise ValueError("Tên người dùng đang trống")
        return f"@{peer}", f"user:{peer.lower()}"

    if _NUMERIC_RE.fullmatch(value):
        return value, f"id:{value}"

    return f"@{value}", f"user:{value.lower()}"


def normalize_message_targets(values: list[str], *, max_targets: int = 200) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        if not (raw or "").strip():
            continue
        display, key = normalize_message_target(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append((display, key))
        if len(unique) > max_targets:
            raise ValueError(f"Tối đa {max_targets} người nhận cho mỗi tác vụ")
    if not unique:
        raise ValueError("Chưa có người nhận hợp lệ")
    return unique


async def eligible_message_accounts(accounts: list[tuple[int, str, str]]) -> tuple[list[tuple[int, str, str]], list[dict]]:
    eligible: list[tuple[int, str, str]] = []
    excluded: list[dict] = []
    for aid, phone, name in accounts:
        cli = manager.get(aid)
        if not cli:
            excluded.append({"id": aid, "name": name, "reason": "chưa kết nối"})
            continue
        remaining = await manager.flood_wait_remaining(aid)
        if remaining > 0:
            excluded.append({"id": aid, "name": name, "reason": f"FloodWait còn khoảng {remaining} giây"})
            continue
        eligible.append((aid, phone, name))
    return eligible, excluded


# Durable message jobs: the HTTP stream observes SQL progress only; the worker
# remains alive if the browser disconnects and can recover after backend restart.
async def multi_target_message_stream(accounts, targets, text: str, parameters_extra: dict | None = None):
    from .message_dispatch_runner import create_message_job, message_dispatch_runner, stream_message_job
    await message_dispatch_runner.start()
    job_id = await create_message_job(accounts, targets, text, parameters_extra)
    async for chunk in stream_message_job(job_id):
        yield chunk
