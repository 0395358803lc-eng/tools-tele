"""scope account phone uniqueness to tenant

Revision ID: d8f0a2b3c4d5
Revises: c7e9f1a2b3c4
"""
from alembic import op

revision = "d8f0a2b3c4d5"
down_revision = "c7e9f1a2b3c4"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_index("ix_accounts_phone", table_name="accounts")
    op.create_index("ix_accounts_phone", "accounts", ["phone"], unique=False)
    op.create_index("uq_accounts_user_phone", "accounts", ["user_id", "phone"], unique=True)

def downgrade():
    op.drop_index("uq_accounts_user_phone", table_name="accounts")
    op.drop_index("ix_accounts_phone", table_name="accounts")
    op.create_index("ix_accounts_phone", "accounts", ["phone"], unique=True)
