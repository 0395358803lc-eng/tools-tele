from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, with_loader_criteria
from sqlalchemy.sql.dml import Delete, Update

from .config import settings
from .tenant import current_tenant_id, in_system_scope


class Base(DeclarativeBase):
    pass


def _tenant_models():
    from .models import TENANT_MODELS, TENANT_TABLE_NAMES
    return TENANT_MODELS, TENANT_TABLE_NAMES


@event.listens_for(Session, "do_orm_execute")
def _tenant_orm_execute(state):
    uid = current_tenant_id()
    if not uid or in_system_scope() or state.execution_options.get("tenant_bypass"):
        return
    models, table_names = _tenant_models()
    statement = state.statement
    if state.is_select:
        for model in models:
            statement = statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.user_id == uid,
                    include_aliases=True,
                )
            )
    elif state.is_update or state.is_delete:
        table = getattr(statement, "table", None)
        if table is not None and table.name in table_names and "user_id" in table.c:
            statement = statement.where(table.c.user_id == uid)
    state.statement = statement

@event.listens_for(Session, "before_flush")
def _tenant_before_flush(session, flush_context, instances):
    uid = current_tenant_id()
    if not uid or in_system_scope():
        return
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if not hasattr(obj, "user_id"):
            continue
        owner = getattr(obj, "user_id", None)
        if obj in session.new and not owner:
            setattr(obj, "user_id", uid)
            continue
        if str(owner or "") != uid:
            raise PermissionError("Cross-tenant ORM write blocked")


_database_url = settings.database_url
_is_sqlite = _database_url.startswith("sqlite")


def _validate_connection_mode() -> None:
    if _is_sqlite or not settings.ENFORCE_SINGLE_INSTANCE:
        return
    url = make_url(_database_url)
    host = (url.host or "").lower()
    if host.endswith(".pooler.supabase.com") and url.port == 6543:
        raise RuntimeError(
            "Supabase Transaction pooler (6543) is not supported because "
            "session-level advisory locks are required. Use Session pooler port 5432."
        )


_validate_connection_mode()
_engine_kwargs = {"echo": False, "future": True}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"timeout": 30}
else:
    _engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_size": max(1, min(50, int(settings.DB_POOL_SIZE))),
        "max_overflow": max(0, min(50, int(settings.DB_MAX_OVERFLOW))),
        "pool_timeout": max(1.0, min(120.0, float(settings.DB_POOL_TIMEOUT_SECONDS))),
        "pool_recycle": max(60, min(86400, int(settings.DB_POOL_RECYCLE_SECONDS))),
        "pool_use_lifo": True,
    })

engine = create_async_engine(_database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


_INSTANCE_LOCK_ID = 77177364013717
_instance_lock_conn = None


async def acquire_instance_lock() -> bool:
    global _instance_lock_conn
    if _is_sqlite or not settings.ENFORCE_SINGLE_INSTANCE:
        return True
    if _instance_lock_conn is not None:
        return True
    conn = await engine.connect()
    try:
        acquired = bool(await conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _INSTANCE_LOCK_ID}
        ))
        if not acquired:
            raise RuntimeError("Another Multi TG Manager instance already holds the database lock")
        _instance_lock_conn = conn
        return True
    except Exception:
        await conn.close()
        raise


async def release_instance_lock() -> None:
    global _instance_lock_conn
    conn = _instance_lock_conn
    _instance_lock_conn = None
    if conn is None:
        return
    try:
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _INSTANCE_LOCK_ID})
    finally:
        await conn.close()


async def init_db():
    await check_db()


async def check_db() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
