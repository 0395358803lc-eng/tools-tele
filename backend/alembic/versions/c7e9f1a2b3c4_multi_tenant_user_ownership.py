"""multi tenant user ownership

Revision ID: c7e9f1a2b3c4
Revises: b6d4f0a9c821
"""
from alembic import op
import sqlalchemy as sa

from app.config import settings

revision = "c7e9f1a2b3c4"
down_revision = "b6d4f0a9c821"
branch_labels = None
depends_on = None

TABLES = [
    "accounts", "telegram_sessions", "security_messages", "gone_accounts",
    "app_settings", "encrypted_secrets", "account_status_history", "bulk_jobs",
    "bulk_job_items", "message_dispatch_items", "phone_check_items",
    "phone_check_accounts", "account_proxies", "audit_logs",
    "target_checks", "target_check_results",
]


def _row_count(bind, table: str) -> int:
    return int(bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def upgrade() -> None:
    bind = op.get_bind()
    owner = (settings.LEGACY_OWNER_USER_ID or "").strip()

    for table in TABLES:
        op.add_column(table, sa.Column("user_id", sa.String(length=36), nullable=True))

    populated = [table for table in TABLES if _row_count(bind, table) > 0]
    if populated and not owner:
        raise RuntimeError(
            "LEGACY_OWNER_USER_ID is required to migrate existing tenant data: "
            + ", ".join(populated)
        )

    if owner:
        for table in TABLES:
            bind.execute(
                sa.text(f'UPDATE "{table}" SET user_id=:uid WHERE user_id IS NULL'),
                {"uid": owner},
            )
        prefix = f"user:{owner}:"
        bind.execute(sa.text(
            "UPDATE app_settings SET key=:p || key WHERE key NOT LIKE 'user:%'"
        ), {"p": prefix})
        bind.execute(sa.text(
            "UPDATE encrypted_secrets SET key=:p || key WHERE key NOT LIKE 'user:%'"
        ), {"p": prefix})

    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", existing_type=sa.String(length=36), nullable=False)
            batch.create_index(f"ix_{table}_user_id", ["user_id"], unique=False)


def downgrade() -> None:
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_column("user_id")
