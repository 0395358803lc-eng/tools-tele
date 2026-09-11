#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/../../.venv/bin/python}"
if [[ "$PY" != "python" && ! -x "$PY" ]]; then PY="python"; fi

if ! command -v initdb >/dev/null 2>&1 && command -v pg_config >/dev/null 2>&1; then
  PG_BINDIR="$(pg_config --bindir 2>/dev/null || true)"
  if [[ -n "$PG_BINDIR" && -x "$PG_BINDIR/initdb" ]]; then
    export PATH="$PG_BINDIR:$PATH"
  fi
fi
for cmd in initdb pg_ctl psql createdb pg_dump pg_restore; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Thiếu binary PostgreSQL để kiểm thử: $cmd" >&2
    exit 2
  fi
done

PORT="${MTM_TEST_PG_PORT:-55432}"
BASE="$(mktemp -d /tmp/mtm_pgverify.XXXXXX)"
PGDATA="$BASE/pgdata"
SRC="$BASE/source.db"
ARCHIVE="$BASE/runtime.tar.gz"
PGUSER_NAME="$(whoami)"

cleanup() {
  if [[ -d "$PGDATA" ]]; then
    pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true
  fi
  rm -rf "$BASE"
}
trap cleanup EXIT

mkdir -p "$BASE/project/backend/sessions" "$BASE/restore"

initdb -D "$PGDATA" -A trust --no-locale -E UTF8 >/dev/null
pg_ctl -D "$PGDATA" -o "-p $PORT -k $BASE" -w start >/dev/null

psql -h "$BASE" -p "$PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE mtm_test" >/dev/null
psql -h "$BASE" -p "$PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE mtm_restore" >/dev/null

PGURL="postgresql://$PGUSER_NAME@127.0.0.1:$PORT/mtm_test"
RESTORE_URL="postgresql://$PGUSER_NAME@127.0.0.1:$PORT/mtm_restore"

echo "[1/10] Alembic -> PostgreSQL"
cd "$ROOT/backend"
DATABASE_URL="$PGURL" DB_URL="" "$PY" -m alembic upgrade head >/dev/null
REV="$(psql "$PGURL" -Atc "select version_num from alembic_version")"
[[ "$REV" == "5f2a1a903d7e" ]]

TYPES="$(psql "$PGURL" -Atc "select column_name||':'||data_type from information_schema.columns where table_name in ('accounts','security_messages','telegram_sessions') and column_name in ('tg_user_id','tg_msg_id','session_ciphertext') order by table_name,column_name")"
grep -q '^tg_user_id:bigint$' <<<"$TYPES"
grep -q '^tg_msg_id:bigint$' <<<"$TYPES"
grep -q '^session_ciphertext:text$' <<<"$TYPES"

echo "[2/10] Kiểm tra nghiêm ngặt DB production"
PREFLIGHT_KEY="$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
set +e
DATABASE_URL="$PGURL" DB_URL="" \
  APP_PASSWORD="integration-only-password" \
  TG_API_ID="12345" TG_API_HASH="0123456789abcdef0123456789abcdef" \
  SECRETS_ENCRYPTION_KEY="$PREFLIGHT_KEY" COOKIE_SECURE="true" TRUST_PROXY_HEADERS="true" \
  ALLOWED_ORIGIN="http://localhost:5173" \
  "$PY" "$ROOT/scripts/production_check.py" --strict --check-db >"$BASE/preflight-bad-origin.log"
BAD_ORIGIN_RC=$?
set -e
[[ "$BAD_ORIGIN_RC" -ne 0 ]]
grep -q 'Dev-only ALLOWED_ORIGIN entries are not allowed in production' "$BASE/preflight-bad-origin.log"

set +e
DATABASE_URL="$PGURL" DB_URL="" \
  APP_PASSWORD="integration-only-password" \
  TG_API_ID="12345" TG_API_HASH="0123456789abcdef0123456789abcdef" \
  SECRETS_ENCRYPTION_KEY="$PREFLIGHT_KEY" COOKIE_SECURE="true" TRUST_PROXY_HEADERS="true" \
  ALLOWED_ORIGIN="" \
  "$PY" "$ROOT/scripts/production_check.py" --strict --check-db >"$BASE/preflight.log"
PREFLIGHT_RC=$?
set -e
[[ "$PREFLIGHT_RC" -ne 0 ]]
grep -q 'PostgreSQL reachable at Alembic head 5f2a1a903d7e' "$BASE/preflight.log"
grep -q 'Deployment target is autoscale' "$BASE/preflight.log"
grep -q 'SUMMARY blockers=1' "$BASE/preflight.log"

echo "[3/10] PostgreSQL singleton advisory lock"
cd "$ROOT/backend"
DATABASE_URL="$PGURL" DB_URL="" ENFORCE_SINGLE_INSTANCE="true" "$PY" - <<'PY'
import asyncio
from sqlalchemy import text
from app.db import _INSTANCE_LOCK_ID, acquire_instance_lock, engine, release_instance_lock

async def main():
    await acquire_instance_lock()
    async with engine.connect() as second:
        acquired = bool(await second.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _INSTANCE_LOCK_ID},
        ))
        assert acquired is False, "second replica unexpectedly acquired singleton lock"
    await release_instance_lock()
    async with engine.connect() as after_release:
        acquired = bool(await after_release.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _INSTANCE_LOCK_ID},
        ))
        assert acquired is True, "singleton lock was not released"
        unlocked = bool(await after_release.scalar(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": _INSTANCE_LOCK_ID},
        ))
        assert unlocked is True

asyncio.run(main())
PY

echo "[4/10] Tạo nguồn SQLite có kiểu dữ liệu"
DB_URL="sqlite+aiosqlite:///$SRC" DATABASE_URL="" "$PY" -m alembic upgrade head >/dev/null
DB_URL="sqlite+aiosqlite:///$SRC" DATABASE_URL="" "$PY" - <<'PY'
import asyncio
from datetime import datetime
from app.db import AsyncSessionLocal
from app.models import (
    Account, AuditLog, BulkJob, EncryptedSecret,
    SecurityMessage, TargetCheck, TelegramSession,
)

async def main():
    async with AsyncSessionLocal() as db:
        acc = Account(
            phone="+10000009999",
            tg_user_id=5000000001,
            first_name="PG",
            last_name="Test",
            username="pg_test",
            bio="migration",
            session_file="acc_pg_test",
            status="connected",
            has_2fa=True,
        )
        db.add(acc)
        await db.flush()
        db.add(SecurityMessage(
            account_id=acc.id,
            tg_msg_id=6000000001,
            message_text="test security message",
            type="login",
            is_read=True,
        ))
        db.add(TelegramSession(
            account_id=acc.id,
            session_file="acc_pg_test",
            status="active",
            is_primary=True,
            session_ciphertext="gAAAAA-test-ciphertext",
        ))
        db.add(EncryptedSecret(
            key="twofa:+10000009999",
            ciphertext="gAAAAA-secret-ciphertext",
        ))
        db.add(BulkJob(
            id="pg-job-test",
            type="integration",
            status="completed",
            parameters={"mode": "typed", "count": 1},
            total=1,
            success=1,
            runner_id="runner-test",
            heartbeat_at=datetime.now(),
        ))
        db.add(AuditLog(
            action="integration:test",
            account_id=acc.id,
            detail={"ok": True, "nested": {"n": 1}},
        ))
        db.add(TargetCheck(
            id="target-pg-test",
            target="@example",
            peer={"id": 5000000001, "type": "user"},
            total=1,
        ))
        await db.commit()

asyncio.run(main())
PY

echo "[5/10] SQLite -> PostgreSQL"
cd "$ROOT"
"$PY" scripts/migrate_sqlite_to_postgres.py --source "$SRC" --target "$PGURL" >/dev/null

echo "[6/10] Xác minh dữ liệu PostgreSQL theo kiểu"
[[ "$(psql "$PGURL" -Atc "select tg_user_id from accounts where phone='+10000009999'")" == "5000000001" ]]
[[ "$(psql "$PGURL" -Atc "select has_2fa from accounts where phone='+10000009999'")" == "t" ]]
[[ "$(psql "$PGURL" -Atc "select tg_msg_id from security_messages")" == "6000000001" ]]
[[ "$(psql "$PGURL" -Atc "select parameters->>'mode' from bulk_jobs where id='pg-job-test'")" == "typed" ]]
[[ "$(psql "$PGURL" -Atc "select (parameters->>'count')::int from bulk_jobs where id='pg-job-test'")" == "1" ]]
[[ "$(psql "$PGURL" -Atc "select peer->>'type' from target_checks where id='target-pg-test'")" == "user" ]]
[[ "$(psql "$PGURL" -Atc "select session_ciphertext from telegram_sessions")" == "gAAAAA-test-ciphertext" ]]
[[ "$(psql "$PGURL" -Atc "select ciphertext from encrypted_secrets")" == "gAAAAA-secret-ciphertext" ]]

echo "[7/10] Từ chối target không trống"
set +e
"$PY" scripts/migrate_sqlite_to_postgres.py --source "$SRC" --target "$PGURL" >"$BASE/retry.log" 2>&1
RETRY_RC=$?
set -e
[[ "$RETRY_RC" -ne 0 ]]
grep -q 'Target PostgreSQL is not empty' "$BASE/retry.log"

echo "[8/10] Kiểm thử scheduler/tải SQL 100 tài khoản trên PostgreSQL"
LOAD_JSON="$(DATABASE_URL="$PGURL" DB_URL="" "$PY" scripts/verify_bulk_load.py --worker --accounts 100 --concurrency 20)"
echo "$LOAD_JSON"
grep -q '"success": 100' <<<"$LOAD_JSON"
grep -q '"failed": 0' <<<"$LOAD_JSON"
grep -q '"pending": 0' <<<"$LOAD_JSON"
grep -q '"skipped": 0' <<<"$LOAD_JSON"

echo "[9/10] PostgreSQL backup -> xác minh -> phục hồi"
DATABASE_URL="$PGURL" DB_URL="" SESSIONS_DIR="$BASE/project/backend/sessions" \
  "$PY" scripts/backup_runtime.py \
  --project-root "$BASE/project" \
  --output "$ARCHIVE" >/dev/null

"$PY" scripts/restore_runtime.py "$ARCHIVE" \
  --project-root "$BASE/restore" \
  --verify-only >/dev/null

"$PY" scripts/restore_runtime.py "$ARCHIVE" \
  --project-root "$BASE/restore" \
  --force \
  --postgres-url "$RESTORE_URL" >/dev/null

echo "[10/10] Xác minh PostgreSQL đã phục hồi"
[[ "$(psql "$RESTORE_URL" -Atc "select count(*) from accounts where phone='+10000009999'")" == "1" ]]
[[ "$(psql "$RESTORE_URL" -Atc "select tg_user_id from accounts where phone='+10000009999'")" == "5000000001" ]]
[[ "$(psql "$RESTORE_URL" -Atc "select parameters->>'mode' from bulk_jobs where id='pg-job-test'")" == "typed" ]]
[[ "$(psql "$RESTORE_URL" -Atc "select version_num from alembic_version")" == "5f2a1a903d7e" ]]
[[ "$(psql "$RESTORE_URL" -Atc "select count(*) from accounts")" == "101" ]]
[[ "$(psql "$RESTORE_URL" -Atc "select count(*) from bulk_job_items where status='ok'")" == "100" ]]

echo "POSTGRES_INTEGRATION_BACKUP_RESTORE_OK"
