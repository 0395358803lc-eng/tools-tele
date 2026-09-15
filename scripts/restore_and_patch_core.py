from pathlib import Path
import re, shutil
ROOT = Path(r"C:\Users\Admin\Downloads\tools-tele-main\tools-tele-main")
BAK = ROOT / ".backup-before-simple-start-20260914-114004"
for name, rel in [("config.py","backend/app/config.py"),("main.py","backend/app/main.py")]:
    shutil.copy2(BAK / name, ROOT / rel)
p = ROOT / "backend/app/config.py"; t = p.read_text(encoding="utf-8")
t, n1 = re.subn(r"\n    SECRETS_ENCRYPTION_KEY: str = \"\"", "", t, count=1)
if n1 != 1: raise SystemExit(f"config replacement={n1}")
p.write_text(t, encoding="utf-8")
p = ROOT / "backend/app/main.py"; t = p.read_text(encoding="utf-8")
t, n2 = re.subn(r"\n    if not settings\.SECRETS_ENCRYPTION_KEY:\r?\n        log\.warning\([^\n]*\)\r?\n", "\n", t, count=1)
if n2 != 1: raise SystemExit(f"main replacement={n2}")
p.write_text(t, encoding="utf-8")
print("restored and patched config/main")