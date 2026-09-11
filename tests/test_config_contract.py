from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ConfigContractTests(unittest.TestCase):
    def test_env_example_covers_every_settings_field(self):
        source = (ROOT / 'backend' / 'app' / 'config.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        fields = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == 'Settings':
                for child in node.body:
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        fields.add(child.target.id)
        env_text = (ROOT / 'backend' / '.env.example').read_text(encoding='utf-8')
        env_keys = set(re.findall(r'^([A-Z][A-Z0-9_]*)=', env_text, re.MULTILINE))
        missing = sorted(field for field in fields if field.isupper() and field not in env_keys)
        self.assertEqual(missing, [])

    def test_env_example_does_not_contain_real_secret_values(self):
        text = (ROOT / 'backend' / '.env.example').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'(?m)^TG_API_HASH=[0-9a-fA-F]{32}$')
        self.assertNotRegex(text, r'(?m)^SECRETS_ENCRYPTION_KEY=[A-Za-z0-9_-]{43}=$')
        self.assertNotRegex(text, r'(?m)^DATABASE_URL=postgres(?:ql)?://[^\s]+$')


if __name__ == '__main__':
    unittest.main()
