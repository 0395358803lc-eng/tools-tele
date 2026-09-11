from __future__ import annotations

from dataclasses import dataclass

from telethon.errors import FloodWaitError


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    category: str
    status: str | None
    retryable: bool
    user_action_required: bool


_BANNED = {"UserDeactivatedBanError"}
_DEACTIVATED = {"UserDeactivatedError"}
_AUTH = {
    "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "SessionPasswordNeededError",
}
_NETWORK = {
    "TimeoutError", "ConnectionError", "ConnectionResetError",
    "ConnectionAbortedError", "ConnectionRefusedError", "OSError",
}
_USER_ACTION = {
    "ChannelsTooMuchError", "UserChannelsTooMuchError", "ChannelPrivateError",
    "ChatAdminRequiredError", "ChatWriteForbiddenError", "UserBannedInChannelError",
    "InviteHashExpiredError", "InviteHashInvalidError", "PasswordHashInvalidError",
    "SessionTooFreshError", "PasswordTooFreshError",
}


def classify_error(exc: Exception) -> ErrorInfo:
    name = type(exc).__name__
    if isinstance(exc, FloodWaitError) or name == "FloodWaitError":
        return ErrorInfo(name, "flood_wait", "flood_wait", True, False)
    if name in _BANNED:
        return ErrorInfo(name, "account_banned", "banned", False, True)
    if name in _DEACTIVATED:
        return ErrorInfo(name, "account_deactivated", "deactivated", False, True)
    if name in _AUTH:
        return ErrorInfo(name, "authentication", "auth_required", False, True)
    if name in _NETWORK or isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ErrorInfo(name, "network", "network_error", True, False)
    if name in _USER_ACTION:
        return ErrorInfo(name, "user_action", None, False, True)
    if name.endswith("Error"):
        return ErrorInfo(name, "telegram_rpc", None, False, False)
    return ErrorInfo(name, "application", None, False, False)
