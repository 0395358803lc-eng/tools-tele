"""per-account proxy settings

Revision ID: 91b8c7d6e5f4
Revises: 6c1d2f4a7b90
Create Date: 2026-09-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "91b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "6c1d2f4a7b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_proxies",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("proxy_type", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password_ciphertext", sa.Text(), nullable=True),
        sa.Column("rdns", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index("ix_account_proxies_enabled", "account_proxies", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_account_proxies_enabled", table_name="account_proxies")
    op.drop_table("account_proxies")
