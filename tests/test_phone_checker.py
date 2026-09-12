import asyncio
import unittest
from datetime import datetime, timezone

from telethon.tl import types

from backend.app.phone_checker import check_phone, normalize_phone, normalize_phone_list


class FakeClient:
    def __init__(self, imported):
        self.imported = imported
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        if request.__class__.__name__ == 'ImportContactsRequest':
            return self.imported
        return True


class PhoneCheckerTests(unittest.TestCase):
    def test_normalize_and_dedupe(self):
        self.assertEqual(normalize_phone('0901234567', 'VN'), '+84901234567')
        self.assertEqual(normalize_phone('84901234567.0', 'VN'), '+84901234567')
        rows, stats = normalize_phone_list(['0901234567', '+84 901 234 567', 'abc'], 'VN')
        self.assertEqual(len(rows), 2)
        self.assertEqual(stats['valid'], 1)
        self.assertEqual(stats['invalid'], 1)
        self.assertEqual(stats['duplicates'], 1)

    def test_found_and_cleanup(self):
        user = types.User(
            id=123456,
            is_self=False,
            contact=True,
            mutual_contact=False,
            deleted=False,
            bot=False,
            bot_chat_history=False,
            bot_nochats=False,
            verified=False,
            restricted=False,
            min=False,
            bot_inline_geo=False,
            support=False,
            scam=False,
            apply_min_photo=False,
            fake=False,
            bot_attach_menu=False,
            premium=False,
            attach_menu_enabled=False,
            bot_can_edit=False,
            close_friend=False,
            stories_hidden=False,
            stories_unavailable=False,
            contact_require_premium=False,
            bot_business=False,
            bot_has_main_app=False,
            access_hash=987654321,
            first_name='Test',
            last_name='User',
            username='testuser',
            phone='84901234567',
            status=types.UserStatusOffline(was_online=datetime.now(timezone.utc)),
        )
        imported = types.contacts.ImportedContacts(imported=[], popular_invites=[], retry_contacts=[], users=[user])
        cli = FakeClient(imported)
        result = asyncio.run(check_phone(cli, '+84901234567', 7))
        self.assertEqual(result.status, 'found')
        self.assertEqual(result.telegram_user_id, 123456)
        self.assertEqual(result.username, 'testuser')
        self.assertEqual(result.presence, 'offline')
        self.assertEqual(len(cli.requests), 2)

    def test_not_discoverable(self):
        imported = types.contacts.ImportedContacts(imported=[], popular_invites=[], retry_contacts=[], users=[])
        result = asyncio.run(check_phone(FakeClient(imported), '+84901234567', 1))
        self.assertEqual(result.status, 'not_discoverable')

    def test_retry_contact(self):
        imported = types.contacts.ImportedContacts(imported=[], popular_invites=[], retry_contacts=[9], users=[])
        result = asyncio.run(check_phone(FakeClient(imported), '+84901234567', 9))
        self.assertEqual(result.status, 'retry_required')


if __name__ == '__main__':
    unittest.main()
