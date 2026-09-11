#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ -x "$ROOT/../../.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/../../.venv/bin/python"
fi

if [[ "${NODE_ENV:-}" == "production" ]]; then
  echo "[kiểm tra] Đang xác minh cấu hình production..."
  "$PYTHON_BIN" "$ROOT/scripts/production_check.py" --strict
fi

echo "[cơ sở dữ liệu] Đang áp dụng Alembic migration..."
"$PYTHON_BIN" -m alembic upgrade head

if [[ "${NODE_ENV:-}" == "production" ]]; then
  echo "[kiểm tra] Đang xác minh kết nối PostgreSQL và schema head..."
  "$PYTHON_BIN" "$ROOT/scripts/production_check.py" --strict --check-db
fi

# Chỉ chạy đúng một worker: Telethon client/listener thuộc phạm vi tiến trình và không được
# nhân bản bằng nhiều Uvicorn worker cho cùng một tập tài khoản Telegram.
exec "$PYTHON_BIN" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1
