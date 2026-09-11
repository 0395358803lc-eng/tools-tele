"""runtime cleanup and job heartbeat

Revision ID: 4c8c1c72e5d0
Revises: 2d91fbc7b23a
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4c8c1c72e5d0"
down_revision: Union[str, Sequence[str], None] = "2d91fbc7b23a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("is_online")
        batch_op.drop_column("last_seen")

    op.drop_table("pending_logins")

    with op.batch_alter_table("bulk_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("runner_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_bulk_jobs_runner_id", ["runner_id"], unique=False)
        batch_op.create_index("ix_bulk_jobs_heartbeat_at", ["heartbeat_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("bulk_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_bulk_jobs_heartbeat_at")
        batch_op.drop_index("ix_bulk_jobs_runner_id")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("runner_id")

    op.create_table(
        "pending_logins",
        sa.Column("phone", sa.String(length=32), primary_key=True),
        sa.Column("phone_code_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_seen", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()))
