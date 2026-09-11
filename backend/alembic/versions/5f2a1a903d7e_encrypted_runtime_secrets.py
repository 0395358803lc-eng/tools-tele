"""encrypted runtime secrets

Revision ID: 5f2a1a903d7e
Revises: 4c8c1c72e5d0
Create Date: 2026-09-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "5f2a1a903d7e"
down_revision: Union[str, Sequence[str], None] = "4c8c1c72e5d0"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("telegram_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("session_ciphertext", sa.Text(), nullable=True))
    op.create_table(
        "encrypted_secrets",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("encrypted_secrets")
    with op.batch_alter_table("telegram_sessions", schema=None) as batch_op:
        batch_op.drop_column("session_ciphertext")
