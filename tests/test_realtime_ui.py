from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'frontend' / 'src'


class RealtimeUiTests(unittest.TestCase):
    def test_authenticated_sse_fetch_contract(self):
        source = (SRC / 'lib' / 'realtime.js').read_text(encoding='utf-8')
        self.assertIn("headers.Authorization = `Bearer ${token}`", source)
        self.assertIn("headers['Last-Event-ID']", source)
        self.assertIn("Accept: 'text/event-stream'", source)
        self.assertIn('response.body.getReader()', source)
        self.assertIn('notifyUnauthorized()', source)
        self.assertNotIn('new EventSource(', source)

    def test_realtime_hook_is_bounded_and_reconnects(self):
        source = (SRC / 'lib' / 'useRealtimeEvents.js').read_text(encoding='utf-8')
        match = re.search(r'MAX_REALTIME_EVENTS\s*=\s*(\d+)', source)
        self.assertIsNotNone(match)
        self.assertLessEqual(int(match.group(1)), 5000)
        self.assertIn('Math.min(15000', source)
        self.assertIn('after_id: cursorRef.current', source)
        self.assertIn('before_id: before', source)

    def test_panel_exposes_operator_controls(self):
        source = (SRC / 'components' / 'RealtimeLogPanel.jsx').read_text(encoding='utf-8')
        for text in ('Tắt tự cuộn', 'Sao chép', 'Xuất JSON', 'Xóa màn hình', 'Tải lịch sử cũ hơn'):
            self.assertIn(text, source)
        self.assertIn('setFeature', source)
        self.assertIn('setLevel', source)

    def test_activity_center_is_wired_into_app(self):
        app = (SRC / 'App.jsx').read_text(encoding='utf-8')
        activity = (SRC / 'tabs' / 'ActivityTab.jsx').read_text(encoding='utf-8')
        self.assertIn("lazy(() => import('./tabs/ActivityTab.jsx'))", app)
        self.assertIn("id: 'activity'", app)
        self.assertIn("<ActivityTab accounts={accounts} />", app)
        self.assertIn('Tác vụ đang hoạt động', activity)
        self.assertIn('Account FloodWait', activity)
        self.assertIn('<RealtimeLogPanel', activity)

    def test_job_detail_reuses_realtime_panel(self):
        source = (SRC / 'tabs' / 'JobsTab.jsx').read_text(encoding='utf-8')
        self.assertIn("import RealtimeLogPanel", source)
        self.assertIn('initialFilters={{ job_id: selected.id }}', source)

    def test_api_has_event_history_and_shared_unauthorized_signal(self):
        source = (SRC / 'lib' / 'api.js').read_text(encoding='utf-8')
        self.assertIn("eventHistory: (params = {}) => api.get('/api/events/history', params)", source)
        self.assertIn('export function notifyUnauthorized()', source)


if __name__ == '__main__':
    unittest.main()
