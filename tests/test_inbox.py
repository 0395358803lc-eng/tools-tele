from datetime import datetime
from types import SimpleNamespace

from telethon.tl.types import User

from backend.app.routers.inbox import _dialog_to_dict
from backend.app.tg_manager import manager


def test_dialog_serialization_keeps_unread_and_marked_peer():
    entity = User(id=12345, first_name="Alice", username="alice")
    message = SimpleNamespace(
        id=9, out=False, message="xin chào", media=None,
        date=datetime(2026, 9, 12, 1, 2, 3), action=None, sender_id=12345,
    )
    dialog = SimpleNamespace(
        entity=entity, message=message, unread_count=2,
        unread_mentions_count=1, pinned=True, folder_id=None,
    )
    row = _dialog_to_dict(dialog)
    assert row["peer"]["ref"] == "12345"
    assert row["title"] == "Alice"
    assert row["unread_count"] == 2
    assert row["last_message"]["text"] == "xin chào"


def test_inbox_activity_filters_by_sequence():
    manager._inbox_events.clear()
    manager._inbox_seq = 2
    manager._inbox_events[7].append({"seq": 1, "account_id": 7, "peer_id": 10})
    manager._inbox_events[8].append({"seq": 2, "account_id": 8, "peer_id": 20})
    try:
        out = manager.inbox_activity(1)
        assert out["latest_seq"] == 2
        assert out["events"] == [{"seq": 2, "account_id": 8, "peer_id": 20}]
    finally:
        manager._inbox_events.clear()
        manager._inbox_seq = 0
