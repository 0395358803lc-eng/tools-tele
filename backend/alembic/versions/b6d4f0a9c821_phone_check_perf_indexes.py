"""phone check performance indexes

Revision ID: b6d4f0a9c821
Revises: a4c9e2f17b63
Create Date: 2026-09-12
"""
from typing import Sequence, Union
from alembic import op

revision: str = "b6d4f0a9c821"
down_revision: Union[str, Sequence[str], None] = "a4c9e2f17b63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_phone_check_items_job_status",
        "phone_check_items",
        ["job_id", "status"],
    )
    op.create_index(
        "ix_phone_check_items_claim",
        "phone_check_items",
        ["job_id", "account_id", "status", "next_retry_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_phone_check_items_claim", table_name="phone_check_items")
    op.drop_index("ix_phone_check_items_job_status", table_name="phone_check_items")
