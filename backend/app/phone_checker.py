from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import phonenumbers
from telethon import utils as telethon_utils
from telethon.errors import FloodWaitError, RpcCallFailError
from telethon.tl import functions, types


TERMINAL_STATUSES = {"found", "not_discoverable", "invalid", "permanent_error"}
RETRYABLE_STATUSES = {"retry_required", "temporary_error", "rate_limited", "in_flight_unknown"}


@dataclass(slots=True)
class PhoneCheckResult:
    status: str
    phone: str
    telegram_user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    presence: str | None = None
    last_online_at: datetime | None = None
    retry_after_seconds: int | None = None
    error_code: str | None = None
    error_detail: str | None = None
    cleanup_error: str | None = None


def normalize_phone(raw: str, default_region: str = "VN") -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]
    compact = "".join(ch for ch in value if ch not in " ().-")
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    region = (default_region or "VN").upper()
    if not compact.startswith("+") and compact.isdigit():
        calling_code = phonenumbers.country_code_for_region(region)
        if calling_code and compact.startswith(str(calling_code)) and len(compact) >= 8:
            compact = "+" + compact
    try:
        parsed = phonenumbers.parse(
            compact,
            None if compact.startswith("+") else region,
        )
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_phone_list(values: list[str], default_region: str = "VN", max_items: int = 50000) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    duplicates = invalid = empty = 0
    for raw in values:
        original = str(raw or "").strip()
        if not original:
            empty += 1
            continue
        normalized = normalize_phone(original, default_region)
        if normalized:
            key = normalized
        else:
            key = f"invalid:{original}"
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if not normalized:
            invalid += 1
        rows.append({"original": original, "normalized": normalized})
        if len(rows) > max_items:
            raise ValueError(f"Tối đa {max_items} số duy nhất cho mỗi tác vụ")
    return rows, {
        "input": len(values),
        "unique": len(rows),
        "valid": sum(1 for row in rows if row["normalized"]),
        "invalid": invalid,
        "duplicates": duplicates,
        "empty": empty,
    }


def _presence(user: Any) -> tuple[str, datetime | None]:
    status = getattr(user, "status", None)
    if isinstance(status, types.UserStatusOnline):
        return "online", None
    if isinstance(status, types.UserStatusOffline):
        return "offline", getattr(status, "was_online", None)
    if isinstance(status, types.UserStatusRecently):
        return "recently", None
    if isinstance(status, types.UserStatusLastWeek):
        return "last_week", None
    if isinstance(status, types.UserStatusLastMonth):
        return "last_month", None
    return "unknown", None


async def _cleanup_contact(client, user) -> str | None:
    last_error = None
    for attempt in range(2):
        try:
            await client(functions.contacts.DeleteContactsRequest(id=[telethon_utils.get_input_user(user)]))
            return None
        except Exception as exc:  # cleanup cannot destroy a FOUND result
            last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if attempt == 0:
                await asyncio.sleep(0.5)
    return last_error or "DeleteContactsRequest failed"


async def check_phone(client, phone: str, client_id: int) -> PhoneCheckResult:
    contact = types.InputPhoneContact(
        client_id=int(client_id),
        phone=phone,
        first_name="",
        last_name="",
    )
    try:
        imported = await client(functions.contacts.ImportContactsRequest([contact]))
    except FloodWaitError as exc:
        return PhoneCheckResult(
            status="rate_limited", phone=phone,
            retry_after_seconds=max(1, int(exc.seconds or 1)),
            error_code="FloodWaitError",
            error_detail=f"Telegram yêu cầu chờ {int(exc.seconds or 1)} giây",
        )
    except RpcCallFailError as exc:
        return PhoneCheckResult(
            status="temporary_error", phone=phone,
            error_code=type(exc).__name__, error_detail=str(exc)[:500],
        )
    except (TimeoutError, ConnectionError, OSError) as exc:
        return PhoneCheckResult(
            status="temporary_error", phone=phone,
            error_code=type(exc).__name__, error_detail=str(exc)[:500],
        )
    except Exception as exc:
        return PhoneCheckResult(
            status="temporary_error", phone=phone,
            error_code=type(exc).__name__, error_detail=str(exc)[:500],
        )

    users = list(getattr(imported, "users", None) or [])
    retry_contacts = list(getattr(imported, "retry_contacts", None) or [])
    if client_id in retry_contacts or phone in retry_contacts:
        return PhoneCheckResult(
            status="retry_required", phone=phone,
            error_code="RETRY_CONTACT", error_detail="Telegram yêu cầu thử lại contact này",
        )
    if not users:
        return PhoneCheckResult(status="not_discoverable", phone=phone)
    if len(users) != 1:
        return PhoneCheckResult(
            status="permanent_error", phone=phone,
            error_code="MULTIPLE_MATCHES", error_detail="Telegram trả về nhiều user ngoài dự kiến",
        )

    user = users[0]
    presence, last_online_at = _presence(user)
    cleanup_error = await _cleanup_contact(client, user)
    return PhoneCheckResult(
        status="found",
        phone=phone,
        telegram_user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        first_name=getattr(user, "first_name", None),
        last_name=getattr(user, "last_name", None),
        presence=presence,
        last_online_at=last_online_at,
        cleanup_error=cleanup_error,
    )
