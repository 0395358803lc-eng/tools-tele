"""Add per-account fallback proxy support.

Revision ID: 1a2b3c4d5e6f
Revises: f0b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa

revision = "1a2b3c4d5e6f"
down_revision = "f0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account_proxies") as batch:
        batch.add_column(sa.Column("fallback_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("fallback_proxy_type", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("fallback_host", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("fallback_port", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("fallback_username", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("fallback_password_ciphertext", sa.Text(), nullable=True))
        batch.add_column(sa.Column("fallback_rdns", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("active_slot", sa.String(length=16), nullable=False, server_default="primary"))
        batch.add_column(sa.Column("failover_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_failover_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("account_proxies") as batch:
        batch.drop_column("last_failover_at")
        batch.drop_column("failover_count")
        batch.drop_column("active_slot")
        batch.drop_column("fallback_rdns")
        batch.drop_column("fallback_password_ciphertext")
        batch.drop_column("fallback_username")
        batch.drop_column("fallback_port")
        batch.drop_column("fallback_host")
        batch.drop_column("fallback_proxy_type")
        batch.drop_column("fallback_enabled")
