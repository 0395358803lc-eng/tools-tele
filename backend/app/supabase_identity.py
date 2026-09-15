from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from supabase import ClientOptions, create_client

from .config import settings

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
USER_EMAIL_DOMAIN = "users.mtm.local"
PASSWORD_MIN_LENGTH = 12


def validate_password(password: str) -> None:
    value = password or ""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError("Mật khẩu phải có ít nhất 12 ký tự")
    if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value):
        raise ValueError("Mật khẩu phải có cả chữ hoa và chữ thường")
    if not re.search(r"\d", value):
        raise ValueError("Mật khẩu phải có ít nhất một chữ số")
    if not re.search(r"[^A-Za-z0-9]", value):
        raise ValueError("Mật khẩu phải có ít nhất một ký tự đặc biệt")


@dataclass(frozen=True)
class IdentityUser:
    id: str
    username: str
    email: str
    role: str
    disabled: bool
    created_at: str | None = None
    last_sign_in_at: str | None = None
    session_not_before: str | None = None
    quotas: dict[str, int] | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def supabase_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_PUBLISHABLE_KEY and settings.SUPABASE_SECRET_KEY)


def _require_config() -> None:
    if not supabase_configured():
        raise RuntimeError("ChÆ°a cáº¥u hÃ¬nh Ä‘áº§y Ä‘á»§ Supabase Identity")


def _server_client():
    _require_config()
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )


def username_to_email(username: str) -> str:
    value = (username or "").strip().lower()
    if "@" in value:
        return value
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("TÃªn Ä‘Äƒng nháº­p chá»‰ gá»“m chá»¯, sá»‘, dáº¥u cháº¥m, gáº¡ch dÆ°á»›i/gáº¡ch ngang vÃ  dÃ i 3-64 kÃ½ tá»±")
    return f"{value}@{USER_EMAIL_DOMAIN}"


def display_username(user: Any) -> str:
    meta = getattr(user, "user_metadata", None) or {}
    return str(meta.get("username") or (getattr(user, "email", "") or "").split("@")[0])


def identity_from_user(user: Any) -> IdentityUser:
    app_meta = getattr(user, "app_metadata", None) or {}
    banned_until = getattr(user, "banned_until", None)
    disabled = False
    if banned_until:
        try:
            dt = datetime.fromisoformat(str(banned_until).replace("Z", "+00:00"))
            disabled = dt > datetime.now(timezone.utc)
        except Exception:
            disabled = True
    return IdentityUser(
        id=str(getattr(user, "id", "")),
        username=display_username(user),
        email=str(getattr(user, "email", "") or ""),
        role=str(app_meta.get("role") or "unprovisioned"),
        disabled=disabled,
        created_at=str(getattr(user, "created_at", "") or "") or None,
        last_sign_in_at=str(getattr(user, "last_sign_in_at", "") or "") or None,
        session_not_before=str(app_meta.get("session_not_before") or "") or None,
        quotas=dict(app_meta.get("quotas") or {}),
    )


def verify_access_token(token: str) -> IdentityUser:
    if not token:
        raise ValueError("Thiáº¿u access token")
    response = _server_client().auth.get_user(token)
    user = getattr(response, "user", None)
    if not user:
        raise ValueError("Access token khÃ´ng há»£p lá»‡")
    identity = identity_from_user(user)
    if identity.disabled:
        raise PermissionError("TÃ i khoáº£n Ä‘Ã£ bá»‹ khÃ³a")
    if identity.role not in {"admin", "user"}:
        raise PermissionError("Tài khoản chưa được ADMIN cấp quyền")
    return identity


def get_identity_user(uid: str) -> IdentityUser:
    response = _server_client().auth.admin.get_user_by_id(uid)
    user = getattr(response, "user", None)
    if not user:
        raise ValueError("Không tìm thấy user")
    return identity_from_user(user)


def token_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def list_users() -> list[IdentityUser]:
    response = _server_client().auth.admin.list_users(page=1, per_page=1000)
    users = getattr(response, "users", None)
    if users is None and isinstance(response, list):
        users = response
    return [identity_from_user(u) for u in (users or [])]


def has_admin() -> bool:
    return any(u.role == "admin" for u in list_users())


def create_identity_user(username: str, password: str, role: str = "user") -> IdentityUser:
    validate_password(password)
    if role not in {"admin", "user"}:
        raise ValueError("Role khÃ´ng há»£p lá»‡")
    email = username_to_email(username)
    response = _server_client().auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"username": username.strip()},
        "app_metadata": {"role": role, "quotas": {}},
    })
    user = getattr(response, "user", None)
    if not user:
        raise RuntimeError("Supabase khÃ´ng tráº£ vá» user vá»«a táº¡o")
    return identity_from_user(user)


def update_identity_user(uid: str, *, role: str | None = None, password: str | None = None,
                         disabled: bool | None = None, quotas: dict | None = None,
                         force_logout: bool = False) -> IdentityUser:
    current_response = _server_client().auth.admin.get_user_by_id(uid)
    current_user = getattr(current_response, "user", None)
    if not current_user:
        raise ValueError("Không tìm thấy user")
    attrs: dict[str, Any] = {}
    app_meta = dict(getattr(current_user, "app_metadata", None) or {})
    metadata_changed = False
    if role is not None:
        if role not in {"admin", "user"}:
            raise ValueError("Role không hợp lệ")
        app_meta["role"] = role
        metadata_changed = True
    if quotas is not None:
        from .quota import normalize_quotas
        app_meta["quotas"] = normalize_quotas(quotas)
        metadata_changed = True
    if password is not None:
        validate_password(password)
        attrs["password"] = password
        force_logout = True
    if disabled is not None:
        attrs["ban_duration"] = "876000h" if disabled else "none"
        force_logout = force_logout or bool(disabled)
    if force_logout:
        app_meta["session_not_before"] = datetime.now(timezone.utc).isoformat()
        metadata_changed = True
    if metadata_changed:
        attrs["app_metadata"] = app_meta
    response = (_server_client().auth.admin.update_user_by_id(uid, attrs)
                if attrs else current_response)
    user = getattr(response, "user", None)
    if not user:
        raise RuntimeError("Không tìm thấy user")
    return identity_from_user(user)


def force_logout_identity_user(uid: str) -> IdentityUser:
    return update_identity_user(uid, force_logout=True)


def delete_identity_user(uid: str) -> None:
    _server_client().auth.admin.delete_user(uid)


def verify_user_password(email: str, password: str) -> bool:
    if not email or not password:
        return False
    try:
        client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_PUBLISHABLE_KEY,
            options=ClientOptions(auto_refresh_token=False, persist_session=False),
        )
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        return bool(getattr(response, "user", None))
    except Exception:
        return False
