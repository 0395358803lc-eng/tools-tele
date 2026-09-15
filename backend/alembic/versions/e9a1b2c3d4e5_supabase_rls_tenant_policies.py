"""Supabase RLS policies for tenant-owned tables.

Revision ID: e9a1b2c3d4e5
Revises: d8f0a2b3c4d5
"""
from alembic import op

revision = "e9a1b2c3d4e5"
down_revision = "d8f0a2b3c4d5"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "accounts", "telegram_sessions", "security_messages", "gone_accounts",
    "app_settings", "encrypted_secrets", "account_status_history",
    "bulk_jobs", "bulk_job_items", "message_dispatch_items",
    "phone_check_items", "phone_check_accounts", "account_proxies",
    "audit_logs", "target_checks", "target_check_results",
)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    has_auth_uid = bind.exec_driver_sql(
        "SELECT to_regprocedure('auth.uid()') IS NOT NULL"
    ).scalar()
    if not has_auth_uid:
        raise RuntimeError("Supabase auth.uid() is required before enabling tenant RLS")

    for table in TENANT_TABLES:
        qtable = _q(table)
        policy = _q(f"tenant_owner_{table}")
        op.execute(f"ALTER TABLE {qtable} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qtable} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {qtable}")
        op.execute(
            f"CREATE POLICY {policy} ON {qtable} FOR ALL TO authenticated "
            f"USING ((select auth.uid())::text = user_id) "
            f"WITH CHECK ((select auth.uid())::text = user_id)"
        )
        # Business data remains backend-only even though RLS is configured.
        op.execute(f"REVOKE ALL ON TABLE {qtable} FROM anon, authenticated")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        qtable = _q(table)
        policy = _q(f"tenant_owner_{table}")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {qtable}")
        op.execute(f"ALTER TABLE {qtable} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qtable} DISABLE ROW LEVEL SECURITY")
