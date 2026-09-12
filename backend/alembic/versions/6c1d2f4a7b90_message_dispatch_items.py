"""message dispatch items

Revision ID: 6c1d2f4a7b90
Revises: 5f2a1a903d7e
Create Date: 2026-09-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "6c1d2f4a7b90"
down_revision: Union[str, Sequence[str], None] = "5f2a1a903d7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_dispatch_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("normalized_target", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["bulk_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("job_id", "normalized_target", name="uq_message_dispatch_job_target"),
    )
    op.create_index("ix_message_dispatch_items_job_id", "message_dispatch_items", ["job_id"])
    op.create_index("ix_message_dispatch_items_account_id", "message_dispatch_items", ["account_id"])
    op.create_index("ix_message_dispatch_items_status", "message_dispatch_items", ["status"])
    op.create_index("ix_message_dispatch_items_job_account", "message_dispatch_items", ["job_id", "account_id"])


def downgrade() -> None:
    op.drop_index("ix_message_dispatch_items_job_account", table_name="message_dispatch_items")
    op.drop_index("ix_message_dispatch_items_status", table_name="message_dispatch_items")
    op.drop_index("ix_message_dispatch_items_account_id", table_name="message_dispatch_items")
    op.drop_index("ix_message_dispatch_items_job_id", table_name="message_dispatch_items")
    op.drop_table("message_dispatch_items")
