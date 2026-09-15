from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"node_modules", ".venv", "backups", "sessions", "logs", "__pycache__"}
EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".bat", ".sh", ".txt", ".toml", ".yaml", ".yml", ".html", ".css"}


def secret_values() -> list[str]:
    env = dotenv_values(ROOT / "backend" / ".env")
    values = []
    for key in ("SUPABASE_SECRET_KEY", "DATABASE_URL"):
        value = str(env.get(key) or "").strip()
        if value:
            values.append(value)
    db = str(env.get("DATABASE_URL") or "")
    try:
        password = urlsplit(db).password or ""
        if len(password) >= 8:
            values.append(password)
    except Exception:
        pass
    key_file = ROOT / "backend" / "sessions" / ".encryption.key"
    if key_file.is_file():
        value = key_file.read_text(encoding="utf-8", errors="ignore").strip()
        if value:
            values.append(value)
    return list(dict.fromkeys(v for v in values if len(v) >= 8))


def main() -> None:
    secrets = secret_values()
    hits = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in rel.parts):
            continue
        if rel.as_posix() == "backend/.env":
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(secret in text for secret in secrets):
            hits.append(rel.as_posix())
    print(f"SCANNED={scanned}")
    print(f"EXACT_SECRET_HITS={len(hits)}")
    if hits:
        for hit in hits:
            print(f"HIT={hit}")
        raise SystemExit(1)
    print("CLEAN=True")


if __name__ == "__main__":
    main()
