"""Harden long-running jobs and message dispatch recovery.

Revision ID: 7f3a9c2d1e4b
Revises: 1a2b3c4d5e6f
"""
from alembic import op
import sqlalchemy as sa

revision = "7f3a9c2d1e4b"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("bulk_jobs") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("paused_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("checkpoint", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("last_error_code", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("last_error_detail", sa.Text(), nullable=True))
    with op.batch_alter_table("message_dispatch_items") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("next_retry_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("processing_token", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_message_dispatch_items_status_retry", ["status", "next_retry_at"], unique=False)
        batch.create_index("ix_message_dispatch_items_processing_token", ["processing_token"], unique=False)


def downgrade():
    with op.batch_alter_table("message_dispatch_items") as batch:
        batch.drop_index("ix_message_dispatch_items_processing_token")
        batch.drop_index("ix_message_dispatch_items_status_retry")
        batch.drop_column("updated_at")
        batch.drop_column("processing_token")
        batch.drop_column("next_retry_at")
        batch.drop_column("max_attempts")

    with op.batch_alter_table("bulk_jobs") as batch:
        batch.drop_column("last_error_detail")
        batch.drop_column("last_error_code")
        batch.drop_column("checkpoint")
        batch.drop_column("resume_count")
        batch.drop_column("paused_at")
        batch.drop_column("updated_at")
