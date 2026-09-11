"""account operational state

Revision ID: 0a63b5f566a7
Revises: 1b822ca2189e
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0a63b5f566a7"
down_revision: Union[str, Sequence[str], None] = "1b822ca2189e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_success_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_ping_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("flood_wait_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_error_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("reconnect_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_index(
            "ix_accounts_flood_wait_until", ["flood_wait_until"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_index("ix_accounts_flood_wait_until")
        batch_op.drop_column("reconnect_count")
        batch_op.drop_column("last_error")
        batch_op.drop_column("last_error_type")
        batch_op.drop_column("flood_wait_until")
        batch_op.drop_column("last_ping_at")
        batch_op.drop_column("last_success_at")
