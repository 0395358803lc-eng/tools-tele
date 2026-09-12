"""Helpers for bulk action delays and FloodWait handling."""
import asyncio
import json
import random
from typing import Awaitable, Callable, Optional
from telethon.errors import FloodWaitError
from .config import settings
from .telegram_errors import classify_error


async def jitter_delay(min_s: float | None = None, max_s: float | None = None):
    lo = min_s if min_s is not None else settings.RATE_MIN
    hi = max_s if max_s is not None else settings.RATE_MAX
    if hi < lo:
        hi = lo
    await asyncio.sleep(random.uniform(lo, hi))


async def read_upload_limited(upload, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read an UploadFile without allowing unbounded memory growth."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Tệp tải lên vượt giới hạn {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


# Map Telethon exception class names -> short, human-friendly explanations.
# Matched by class name so we don't need to import every error type.
_ERROR_MESSAGES = {
    "ChannelsTooMuchError": "Tài khoản này đã tham gia quá nhiều nhóm/kênh (giới hạn Telegram khoảng 500). Hãy rời bớt trước.",
    "UserChannelsTooMuchError": "Tài khoản này đã tham gia quá nhiều nhóm/kênh. Hãy rời bớt trước.",
    "ChannelPrivateError": "Kênh/nhóm ở chế độ riêng tư, hoặc tài khoản này đã bị xóa/cấm khỏi đó.",
    "InviteHashExpiredError": "Liên kết mời đã hết hạn.",
    "InviteHashInvalidError": "Liên kết mời không hợp lệ.",
    "InviteHashEmptyError": "Liên kết mời trống hoặc không hợp lệ.",
    "UsernameNotOccupiedError": "Không tồn tại tên người dùng này — hiện chưa có ai sử dụng.",
    "UsernameInvalidError": "Tên người dùng không hợp lệ (5–32 ký tự, gồm chữ/số/gạch dưới và phải bắt đầu bằng chữ cái).",
    "UsernameOccupiedError": "Tên người dùng này đã được sử dụng.",
    "UsernamePurchaseAvailableError": "Tên người dùng này đang được giữ/rao bán — hãy chọn tên khác.",
    "ReactionInvalidError": "Cuộc trò chuyện này không cho phép cảm xúc đó.",
    "ReactionEmptyError": "Không có cảm xúc nào được gửi.",
    "ReactionsTooManyError": "Quá nhiều cảm xúc — cuộc trò chuyện này cho phép ít hơn.",
    "ChatWriteForbiddenError": "Bạn không có quyền thực hiện thao tác này tại đây.",
    "ChatAdminRequiredError": "Thao tác này yêu cầu quyền quản trị viên.",
    "ChatGuestSendForbiddenError": "Bạn phải tham gia cuộc trò chuyện trước khi thực hiện thao tác này.",
    "ChatRestrictedError": "Cuộc trò chuyện này bị hạn chế đối với tài khoản này.",
    "ChatForbiddenError": "Tài khoản này không thể truy cập cuộc trò chuyện.",
    "MsgIdInvalidError": "Không tìm thấy bài viết (ID tin nhắn/liên kết không hợp lệ).",
    "MessageIdInvalidError": "Không tìm thấy bài viết (ID tin nhắn/liên kết không hợp lệ).",
    "PeerIdInvalidError": "Tài khoản này không thể truy cập cuộc trò chuyện.",
    "UserDeactivatedBanError": "Tài khoản này đã bị Telegram cấm/vô hiệu hóa.",
    "UserDeactivatedError": "Tài khoản này đã bị vô hiệu hóa.",
    "AuthKeyUnregisteredError": "Phiên đã hết hiệu lực — hãy kết nối lại tài khoản.",
    "UserBannedInChannelError": "Tài khoản này bị cấm gửi nội dung tại đây.",
    "UserAlreadyParticipantError": "Đã là thành viên.",
    "InviteRequestSentError": "Đã gửi yêu cầu tham gia — đang chờ quản trị viên phê duyệt.",
    "UserAlreadyInvitedError": "Yêu cầu tham gia đã được gửi — đang chờ phê duyệt.",
    "UsersTooMuchError": "Nhóm/kênh này đã đầy.",
    "PasswordHashInvalidError": "Mật khẩu 2FA hiện tại không đúng.",
    "FreshResetAuthorisationForbiddenError": "Telegram đang chặn thay đổi 2FA trên phiên vừa thêm — hãy thử lại sau.",
    "PasswordTooFreshError": "2FA vừa được thay đổi gần đây — Telegram yêu cầu chờ trước khi đổi lại.",
    "SessionTooFreshError": "Phiên này còn quá mới — Telegram yêu cầu chờ trước khi thay đổi 2FA.",
    "DocumentInvalidError": "Emoji tùy chỉnh này không hợp lệ cho cuộc trò chuyện.",
}


def public_error_message(error_type: str | None) -> str | None:
    """Map a persisted exception type to a browser-safe message without raw detail."""
    if not error_type:
        return None
    if error_type == "FloodWaitError":
        return "Telegram đang giới hạn tốc độ; hãy chờ hết thời gian đếm ngược rồi thử lại."
    if error_type in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[error_type]
    if error_type in {
        "TimeoutError", "ConnectionError", "ConnectionResetError",
        "ConnectionAbortedError", "ConnectionRefusedError", "OSError",
    }:
        return "Lỗi mạng tạm thời — có thể thử lại tài khoản."
    if error_type in {
        "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
        "SessionExpiredError", "SessionPasswordNeededError",
    }:
        return "Phiên Telegram không còn được xác thực — hãy kết nối lại tài khoản."
    return f"{error_type}: thao tác thất bại. Hãy kiểm tra nhật ký máy chủ để biết chi tiết."


def friendly_error(e: Exception) -> str:
    if isinstance(e, FloodWaitError):
        return f"Bị giới hạn tốc độ — hãy chờ {e.seconds} giây trước khi thử lại."
    name = type(e).__name__
    if name in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[name]
    info = classify_error(e)
    if info.category == "network":
        return "Lỗi mạng tạm thời — có thể thử lại tài khoản."
    if info.category == "authentication":
        return "Phiên Telegram không còn được xác thực — hãy kết nối lại tài khoản."
    return f"{name}: thao tác thất bại. Hãy kiểm tra nhật ký máy chủ để biết chi tiết."


# Errors that aren't real failures — they're expected conditions where the
# action simply can't apply (account full, chat disallows the reaction, group
# full). We surface these as a soft "skipped" with a plain reason instead of a
# scary red "failed", so a bulk run still finishes cleanly.
SOFT_SKIP_ERRORS = {
    "ChannelsTooMuchError",     # account is in too many groups/channels (~500 cap)
    "UserChannelsTooMuchError", # same, alternate name
    "ReactionInvalidError",     # this chat doesn't allow that reaction
    "ReactionEmptyError",       # reaction not accepted
    "ReactionsTooManyError",    # chat allows fewer reactions
    "UsersTooMuchError",        # group/channel is full
    "UserAlreadyParticipantError",  # đã là thành viên — nothing to do
    "DocumentInvalidError",     # custom emoji not allowed here
}


def is_soft_error(e: Exception) -> bool:
    return type(e).__name__ in SOFT_SKIP_ERRORS


class BulkPacer:
    """Serialize action start times while still allowing bounded in-flight work."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._next_start = 0.0

    async def wait_turn(self):
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next_start > now:
                await asyncio.sleep(self._next_start - now)
            lo = max(0.0, float(getattr(settings, "RATE_MIN", 0.7)))
            hi = max(lo, float(getattr(settings, "RATE_MAX", 1.5)))
            self._next_start = loop.time() + random.uniform(lo, hi)


async def bulk_stream(
    accounts: list[tuple[int, str, str]],
    action: Callable[[object, int], Awaitable[tuple[str, str]]],
    on_success: Optional[Callable[[int], None]] = None,
    concurrency: int | None = None,
    job_type: str = "bulk_action",
    job_parameters: dict | None = None,
):
    """Run a persisted bulk action with pacing, FloodWait protection and progress."""
    from .tg_manager import manager
    from . import job_store

    # Duplicate account ids are ignored so SQL job-item uniqueness is stable.
    seen: set[int] = set()
    unique_accounts: list[tuple[int, str, str]] = []
    for row in accounts:
        if row[0] not in seen:
            seen.add(row[0])
            unique_accounts.append(row)
    accounts = unique_accounts

    total = len(accounts)
    conc = concurrency if concurrency is not None else getattr(settings, "CONCURRENCY", 8)
    try:
        conc = max(1, min(50, int(conc)))
    except (TypeError, ValueError):
        conc = 8

    job_id = await job_store.create_job(job_type, accounts, job_parameters)
    success = failed = skipped = pending = 0
    results: list[dict] = []
    sem = asyncio.Semaphore(conc)
    pacer = BulkPacer()
    out_q: asyncio.Queue = asyncio.Queue()

    async def finish_row(row: dict):
        await job_store.mark_item_result(
            job_id,
            row["id"],
            row["status"],
            row.get("detail", ""),
            row.get("error_code"),
        )
        await out_q.put(row)

    async def worker(aid: int, phone: str, name: str):
        if await job_store.is_cancelled(job_id):
            await finish_row({
                "id": aid, "phone": phone, "name": name,
                "status": "skipped", "detail": "đã hủy trước khi bắt đầu",
                "error_code": "cancelled",
            })
            return

        cli = manager.get(aid)
        if not cli:
            await finish_row({
                "id": aid, "phone": phone, "name": name,
                "status": "skipped", "detail": "chưa kết nối",
                "error_code": "not_connected",
            })
            return

        remaining = await manager.flood_wait_remaining(aid)
        if remaining > 0:
            await finish_row({
                "id": aid, "phone": phone, "name": name,
                "status": "pending",
                "detail": f"Đang bị giới hạn tốc độ — thử lại sau khoảng {remaining} giây.",
                "error_code": "FloodWaitError",
            })
            return

        await pacer.wait_turn()
        if await job_store.is_cancelled(job_id):
            await finish_row({
                "id": aid, "phone": phone, "name": name,
                "status": "skipped", "detail": "đã hủy trước khi thực hiện thao tác",
                "error_code": "cancelled",
            })
            return

        async with manager.account_operation(aid, job_type):
            async with sem:
                await job_store.mark_item_started(job_id, aid)
                try:
                    timeout_s = max(0.1, float(getattr(settings, "TG_RPC_TIMEOUT_SECONDS", 45.0)))
                    status, detail = await asyncio.wait_for(action(cli, aid), timeout=timeout_s)
                    if status not in ("pending", "skipped"):
                        status = "ok"
                    if status in ("ok", "pending"):
                        if on_success:
                            on_success(aid)
                        if status == "ok":
                            await manager.mark_operation_success(aid)
                    row = {
                        "id": aid, "phone": phone, "name": name,
                        "status": status, "detail": detail,
                    }
                except asyncio.TimeoutError as exc:
                    await manager.mark_operation_error(aid, exc)
                    row = {
                        "id": aid, "phone": phone, "name": name,
                        "status": "failed",
                        "detail": f"Thao tác Telegram hết thời gian chờ sau {timeout_s:.0f} giây.",
                        "error_code": "TimeoutError",
                    }
                except FloodWaitError as exc:
                    await manager.mark_flood_wait(aid, exc.seconds)
                    row = {
                        "id": aid, "phone": phone, "name": name,
                        "status": "pending",
                        "detail": friendly_error(exc),
                        "error_code": type(exc).__name__,
                    }
                except Exception as exc:
                    await manager.mark_operation_error(aid, exc)
                    soft = is_soft_error(exc)
                    row = {
                        "id": aid, "phone": phone, "name": name,
                        "status": "skipped" if soft else "failed",
                        "detail": friendly_error(exc),
                        "error_code": type(exc).__name__,
                    }
        await finish_row(row)

    tasks = [asyncio.create_task(worker(aid, phone, name)) for aid, phone, name in accounts]

    try:
        for done_count in range(1, total + 1):
            row = await out_q.get()
            status = row["status"]
            if status == "pending":
                pending += 1
            elif status == "ok":
                success += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
            results.append(row)
            await job_store.update_counts(
                job_id,
                success=success,
                failed=failed,
                skipped=skipped,
                pending=pending,
            )
            yield json.dumps({
                "type": "progress", "job_id": job_id,
                "current": done_count, "total": total,
                "account_name": row.get("name", ""), "status": status,
                "detail": row.get("detail", ""),
                "success": success, "failed": failed,
                "skipped": skipped, "pending": pending,
            }) + "\n"
    except BaseException:
        await job_store.request_cancel(job_id)
        raise
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)

    cancelled = await job_store.is_cancelled(job_id)
    final_status = "cancelled" if cancelled else ("completed_with_errors" if failed else "completed")
    await job_store.finish_job(
        job_id,
        final_status,
        success=success,
        failed=failed,
        skipped=skipped,
        pending=pending,
    )

    yield json.dumps({
        "type": "done", "job_id": job_id, "status": final_status,
        "total": total,
        "success": success, "failed": failed,
        "skipped": skipped, "pending": pending,
        "results": results,
    }) + "\n"
