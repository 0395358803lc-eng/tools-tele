from __future__ import annotations

import io
import unittest

from openpyxl import Workbook

from backend.app.recipient_import import parse_recipient_file
from backend.app.message_dispatch import normalize_message_targets


class RecipientImportTests(unittest.TestCase):
    def test_csv_detects_recipient_columns(self):
        data = 'name,username,phone\nA,@alice,+84901111111\nB,bob,+84902222222\n'.encode()
        parsed = parse_recipient_file('recipients.csv', data)
        self.assertEqual(parsed['columns'], ['username', 'phone'])
        targets = normalize_message_targets(parsed['raw_targets'])
        self.assertEqual([x[0] for x in targets], ['@alice', '+84901111111', '@bob', '+84902222222'])

    def test_xlsx_single_named_column_and_dedupe(self):
        wb = Workbook()
        ws = wb.active
        ws.append(['usname'])
        ws.append(['@alice'])
        ws.append(['alice'])
        ws.append(['https://t.me/bob'])
        buf = io.BytesIO(); wb.save(buf)
        parsed = parse_recipient_file('recipients.xlsx', buf.getvalue())
        targets = normalize_message_targets(parsed['raw_targets'])
        self.assertEqual([x[0] for x in targets], ['@alice', '@bob'])

    def test_unknown_multicolumn_file_is_rejected(self):
        data = 'name,email\nAlice,a@example.com\n'.encode()
        with self.assertRaisesRegex(ValueError, 'Không xác định được cột'):
            parse_recipient_file('bad.csv', data)


if __name__ == '__main__':
    unittest.main()
