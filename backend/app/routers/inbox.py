from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from telethon import utils
from telethon.errors import FloodWaitError

from ..audit import log_audit
from ..schemas import ChatSendIn
from ..tg_manager import SERVICE_ID, manager
from ..utils import friendly_error
from .messaging import _coerce_peer, _history, _msg_to_dict, _peer_info

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


class InboxPeerIn(BaseModel):
    peer: str


def _client(account_id: int):
    cli = manager.get(account_id)
    if not cli:
        raise HTTPException(409, "Tài khoản chưa kết nối")
    return cli


async def _resolve_entity(cli, peer: str):
    ref = _coerce_peer(peer)
    try:
        return await cli.get_entity(ref)
    except Exception:
        async for dialog in cli.iter_dialogs(limit=100):
            if str(dialog.id) == str(peer):
                return dialog.entity
        raise


def _dialog_to_dict(dialog) -> dict:
    entity = dialog.entity
    info = _peer_info(entity)
    marked_id = utils.get_peer_id(entity)
    info["ref"] = str(marked_id)
    last = _msg_to_dict(dialog.message) if dialog.message else None
    return {
        "peer": info,
        "title": info["title"],
        "username": info.get("username"),
        "kind": info.get("kind"),
        "unread_count": int(getattr(dialog, "unread_count", 0) or 0),
        "unread_mentions": int(getattr(dialog, "unread_mentions_count", 0) or 0),
        "pinned": bool(getattr(dialog, "pinned", False)),
        "archived": bool(getattr(dialog, "folder_id", None) == 1),
        "last_message": last,
    }


@router.get("/activity")
async def inbox_activity(since_seq: int = 0):
    since_seq = max(0, int(since_seq or 0))
    return manager.inbox_activity(since_seq)


@router.get("/{account_id}/dialogs")
async def inbox_dialogs(account_id: int, limit: int = 60, unread_only: bool = False):
    cli = _client(account_id)
    limit = max(1, min(100, int(limit)))

    async def collect():
        rows = []
        async for dialog in cli.iter_dialogs(limit=limit):
            entity_id = getattr(dialog.entity, "id", None)
            if entity_id == SERVICE_ID:
                continue
            row = _dialog_to_dict(dialog)
            if unread_only and row["unread_count"] <= 0:
                continue
            rows.append(row)
        return rows

    try:
        dialogs = await asyncio.wait_for(collect(), timeout=45)
        await manager.mark_operation_success(account_id)
        return {
            "account_id": account_id,
            "dialogs": dialogs,
            "unread_total": sum(row["unread_count"] for row in dialogs),
        }
    except Exception as exc:
        await manager.mark_operation_error(account_id, exc)
        raise HTTPException(400, friendly_error(exc))


@router.get("/{account_id}/history")
async def inbox_history(account_id: int, peer: str, limit: int = 50):
    cli = _client(account_id)
    try:
        entity = await _resolve_entity(cli, peer)
        info = _peer_info(entity)
        info["ref"] = str(utils.get_peer_id(entity))
        messages = await asyncio.wait_for(_history(cli, entity, limit), timeout=45)
        return {"peer": info, "messages": messages}
    except Exception as exc:
        raise HTTPException(400, friendly_error(exc))


@router.post("/{account_id}/read")
async def inbox_mark_read(account_id: int, body: InboxPeerIn):
    cli = _client(account_id)
    try:
        entity = await _resolve_entity(cli, body.peer)
        await asyncio.wait_for(cli.send_read_acknowledge(entity, clear_mentions=True), timeout=30)
        await log_audit("inbox:mark_read", account_id, {"peer": body.peer})
        return {"ok": True}
    except FloodWaitError as exc:
        await manager.mark_flood_wait(account_id, exc.seconds)
        raise HTTPException(429, friendly_error(exc))
    except Exception as exc:
        await manager.mark_operation_error(account_id, exc)
        raise HTTPException(400, friendly_error(exc))


@router.post("/{account_id}/reply")
async def inbox_reply(account_id: int, body: ChatSendIn):
    cli = _client(account_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "Tin nhắn đang trống")
    try:
        async with manager.account_operation(account_id, "inbox_reply"):
            entity = await _resolve_entity(cli, body.peer)
            sent = await asyncio.wait_for(cli.send_message(entity, text), timeout=45)
        await manager.mark_operation_success(account_id)
        await log_audit("inbox:reply", account_id, {"peer": body.peer})
        return {"ok": True, "message": _msg_to_dict(sent)}
    except FloodWaitError as exc:
        await manager.mark_flood_wait(account_id, exc.seconds)
        raise HTTPException(429, friendly_error(exc))
    except asyncio.TimeoutError as exc:
        await manager.mark_operation_error(account_id, exc)
        raise HTTPException(504, "Hết thời gian chờ Telegram; hãy kiểm tra lịch sử trước khi gửi lại để tránh trùng tin.")
    except Exception as exc:
        await manager.mark_operation_error(account_id, exc)
        raise HTTPException(400, friendly_error(exc))
