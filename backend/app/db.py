from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


_database_url = settings.database_url
_is_sqlite = _database_url.startswith("sqlite")

_engine_kwargs = {
    "echo": False,
    "future": True,
}
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
    """Hold a PostgreSQL advisory lock for the lifetime of this app process."""
    global _instance_lock_conn
    if _is_sqlite or not settings.ENFORCE_SINGLE_INSTANCE:
        return True
    if _instance_lock_conn is not None:
        return True
    conn = await engine.connect()
    try:
        acquired = bool(await conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _INSTANCE_LOCK_ID},
        ))
        if not acquired:
            raise RuntimeError(
                "Another Multi TG Manager instance already holds the production database lock. "
                "Use exactly one application replica for this account set."
            )
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
        await conn.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": _INSTANCE_LOCK_ID},
        )
    finally:
        await conn.close()


async def init_db():
    """Validate database connectivity only. Schema ownership belongs to Alembic."""
    await check_db()


async def check_db() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
