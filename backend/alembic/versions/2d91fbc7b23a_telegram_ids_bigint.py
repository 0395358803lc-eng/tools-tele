"""telegram ids bigint

Revision ID: 2d91fbc7b23a
Revises: 0a63b5f566a7
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2d91fbc7b23a"
down_revision: Union[str, Sequence[str], None] = "0a63b5f566a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_user_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
        )
    with op.batch_alter_table("gone_accounts", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_user_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
        )
    with op.batch_alter_table("security_messages", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_msg_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("security_messages", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_msg_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False
        )
    with op.batch_alter_table("gone_accounts", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_user_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
        )
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column(
            "tg_user_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
        )
