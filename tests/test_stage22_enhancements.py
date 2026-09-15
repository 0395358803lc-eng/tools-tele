from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.recipient_import import extract_recipient_columns, preview_recipient_file

ROOT = Path(__file__).resolve().parents[1]


class Stage22EnhancementTests(unittest.TestCase):
    def test_preview_and_manual_column_mapping(self):
        data = (
            'Name,Contact,Note\n'
            'Alice,@alice,ok\n'
            'Bob,+84901234567,ok\n'
        ).encode('utf-8')
        preview = preview_recipient_file('people.csv', data)
        self.assertFalse(preview['header_detected'])
        self.assertEqual(preview['column_count'], 3)
        self.assertEqual(preview['sample'][0][1], 'Contact')
        mapped = extract_recipient_columns('people.csv', data, [1], True)
        self.assertEqual(mapped['raw_targets'], ['@alice', '+84901234567'])
        self.assertEqual(mapped['columns'], ['Contact'])
    def test_jobs_exports_and_delivery_contract(self):
        source = (ROOT / 'backend/app/routers/jobs.py').read_text(encoding='utf-8')
        self.assertIn('@router.get("/{job_id}/export.csv")', source)
        self.assertIn('@router.get("/{job_id}/export.xlsx")', source)
        self.assertIn('"delivery_rate"', source)
        self.assertIn('"safe_retry"', source)
        self.assertIn('MessageDispatchItem.attempts == 0', source)

    def test_inbox_server_search_and_pagination_contract(self):
        source = (ROOT / 'backend/app/routers/inbox.py').read_text(encoding='utf-8')
        self.assertIn('q: str = "", offset: int = 0', source)
        self.assertIn('scan_limit = 300 if needle', source)
        self.assertIn('"has_more": len(rows) > offset + limit', source)
        self.assertIn('"next_offset": offset + len(page)', source)

    def test_frontend_wires_mapping_exports_and_pagination(self):
        api = (ROOT / 'frontend/src/lib/api.js').read_text(encoding='utf-8')
        messaging = (ROOT / 'frontend/src/tabs/MessagingTab.jsx').read_text(encoding='utf-8')
        jobs = (ROOT / 'frontend/src/tabs/JobsTab.jsx').read_text(encoding='utf-8')
        inbox = (ROOT / 'frontend/src/tabs/InboxTab.jsx').read_text(encoding='utf-8')
        self.assertIn('previewMessageTargets', api)
        self.assertIn('selected_columns', api)
        self.assertIn('downloadJobExport', api)
        self.assertIn('Nhập cột đã chọn', messaging)
        self.assertIn('selected.delivery.delivery_rate', jobs)
        self.assertIn('Tải thêm hội thoại', inbox)


if __name__ == '__main__':
    unittest.main()
