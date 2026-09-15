from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseBaselineTests(unittest.TestCase):
    def test_versions_match_v1(self):
        root_pkg = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        front_pkg = json.loads((ROOT / 'frontend/package.json').read_text(encoding='utf-8'))
        self.assertEqual(root_pkg['version'], '1.0.0')
        self.assertEqual(front_pkg['version'], '1.0.0')

    def test_python_direct_dependencies_are_pinned(self):
        lines = [x.strip() for x in (ROOT / 'backend/requirements.txt').read_text(encoding='utf-8').splitlines() if x.strip() and not x.startswith('#')]
        self.assertTrue(lines)
        self.assertTrue(all('==' in line for line in lines))

    def test_frontend_uses_lazy_module_splitting(self):
        source = (ROOT / 'frontend/src/App.jsx').read_text(encoding='utf-8')
        self.assertIn("lazy(() => import('./components/AdminPage.jsx'))", source)
        self.assertIn("lazy(() => import('./tabs/MessagingTab.jsx'))", source)
        self.assertIn('<Suspense', source)
