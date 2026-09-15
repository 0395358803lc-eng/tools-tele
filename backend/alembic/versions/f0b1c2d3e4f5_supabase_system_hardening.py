"""Supabase system table hardening and missing FK indexes.

Revision ID: f0b1c2d3e4f5
Revises: e9a1b2c3d4e5
"""
from alembic import op

revision = "f0b1c2d3e4f5"
down_revision = "e9a1b2c3d4e5"
branch_labels = None
depends_on = None

SYSTEM_TABLES = (
    "app_sessions",
    "login_attempts",
    "alembic_version",
)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade():
    bind = op.get_bind()
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_account_id ON audit_logs (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_target_check_results_account_id ON target_check_results (account_id)")
    if bind.dialect.name != "postgresql":
        return
    for table in SYSTEM_TABLES:
        qtable = _q(table)
        policy = _q(f"deny_data_api_{table}")
        op.execute(f"ALTER TABLE {qtable} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qtable} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {qtable} FROM anon, authenticated")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {qtable}")
        op.execute(
            f"CREATE POLICY {policy} ON {qtable} FOR ALL TO anon, authenticated "
            "USING (false) WITH CHECK (false)"
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in SYSTEM_TABLES:
            qtable = _q(table)
            policy = _q(f"deny_data_api_{table}")
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {qtable}")
            op.execute(f"ALTER TABLE {qtable} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {qtable} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_account_id")
    op.execute("DROP INDEX IF EXISTS ix_target_check_results_account_id")
