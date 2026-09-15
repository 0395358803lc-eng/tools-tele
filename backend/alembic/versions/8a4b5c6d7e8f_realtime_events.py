"""Realtime operational events for user-visible live logs.

Revision ID: 8a4b5c6d7e8f
Revises: 7f3a9c2d1e4b
"""
from alembic import op
import sqlalchemy as sa

revision = "8a4b5c6d7e8f"
down_revision = "7f3a9c2d1e4b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "realtime_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("feature", sa.String(length=48), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False, server_default="event"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_realtime_events_user_id", "realtime_events", ["user_id"])
    op.create_index("ix_realtime_events_created_at", "realtime_events", ["created_at"])
    op.create_index("ix_realtime_events_account_id", "realtime_events", ["account_id"])
    op.create_index("ix_realtime_events_user_cursor", "realtime_events", ["user_id", "id"])
    op.create_index("ix_realtime_events_user_feature_cursor", "realtime_events", ["user_id", "feature", "id"])
    op.create_index("ix_realtime_events_user_job_cursor", "realtime_events", ["user_id", "job_id", "id"])
    op.create_index("ix_realtime_events_user_level_cursor", "realtime_events", ["user_id", "level", "id"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    has_auth_uid = bind.exec_driver_sql(
        "SELECT to_regprocedure('auth.uid()') IS NOT NULL"
    ).scalar()
    if not has_auth_uid:
        raise RuntimeError("Supabase auth.uid() is required before enabling realtime event RLS")
    op.execute("ALTER TABLE realtime_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE realtime_events FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_owner_realtime_events ON realtime_events")
    op.execute(
        "CREATE POLICY tenant_owner_realtime_events ON realtime_events FOR ALL TO authenticated "
        "USING ((select auth.uid())::text = user_id) "
        "WITH CHECK ((select auth.uid())::text = user_id)"
    )
    op.execute("REVOKE ALL ON TABLE realtime_events FROM anon, authenticated")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_owner_realtime_events ON realtime_events")
        op.execute("ALTER TABLE realtime_events NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE realtime_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_realtime_events_user_level_cursor", table_name="realtime_events")
    op.drop_index("ix_realtime_events_user_job_cursor", table_name="realtime_events")
    op.drop_index("ix_realtime_events_user_feature_cursor", table_name="realtime_events")
    op.drop_index("ix_realtime_events_user_cursor", table_name="realtime_events")
    op.drop_index("ix_realtime_events_account_id", table_name="realtime_events")
    op.drop_index("ix_realtime_events_created_at", table_name="realtime_events")
    op.drop_index("ix_realtime_events_user_id", table_name="realtime_events")
    op.drop_table("realtime_events")
