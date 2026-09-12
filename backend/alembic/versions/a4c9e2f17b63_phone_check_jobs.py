"""phone check jobs

Revision ID: a4c9e2f17b63
Revises: 91b8c7d6e5f4
Create Date: 2026-09-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a4c9e2f17b63"
down_revision: Union[str, Sequence[str], None] = "91b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phone_check_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("original_phone", sa.String(length=64), nullable=False),
        sa.Column("normalized_phone", sa.String(length=32), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("presence", sa.String(length=32), nullable=True),
        sa.Column("last_online_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("processing_token", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["bulk_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("job_id", "dedupe_key", name="uq_phone_check_job_phone"),
    )
    op.create_index("ix_phone_check_items_job_id", "phone_check_items", ["job_id"])
    op.create_index("ix_phone_check_items_account_id", "phone_check_items", ["account_id"])
    op.create_index("ix_phone_check_items_normalized_phone", "phone_check_items", ["normalized_phone"])
    op.create_index("ix_phone_check_items_status", "phone_check_items", ["status"])
    op.create_index("ix_phone_check_items_next_retry_at", "phone_check_items", ["next_retry_at"])
    op.create_index("ix_phone_check_items_processing_token", "phone_check_items", ["processing_token"])
    op.create_index("ix_phone_check_items_status_retry", "phone_check_items", ["status", "next_retry_at"])
    op.create_index("ix_phone_check_items_job_account", "phone_check_items", ["job_id", "account_id"])

    op.create_table(
        "phone_check_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("found", sa.Integer(), nullable=False),
        sa.Column("not_discoverable", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["bulk_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("job_id", "account_id", name="uq_phone_check_job_account"),
    )
    op.create_index("ix_phone_check_accounts_job_id", "phone_check_accounts", ["job_id"])
    op.create_index("ix_phone_check_accounts_account_id", "phone_check_accounts", ["account_id"])
    op.create_index("ix_phone_check_accounts_status", "phone_check_accounts", ["status"])


def downgrade() -> None:
    op.drop_table("phone_check_accounts")
    op.drop_table("phone_check_items")
