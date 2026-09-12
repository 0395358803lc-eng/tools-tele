from contextlib import asynccontextmanager, suppress
import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .logging_config import configure_logging
from .db import acquire_instance_lock, init_db, release_instance_lock
from .system_status import readiness
from .tg_manager import manager
from .runtime_settings import load_runtime_settings
from .job_store import recover_interrupted_jobs
from .phone_check_runner import phone_check_runner
from . import secrets_store
from .auth import router as auth_router, require_auth, cleanup_auth_state
from .security_middleware import BrowserSecurityMiddleware
from .routers import accounts, profile, security, groups, messaging, inbox, proxies, phone_checks, settings as settings_router, bulk, jobs, audit, system

configure_logging()
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # validate critical env
    if not settings.APP_PASSWORD:
        log.warning("APP_PASSWORD is empty — set it in backend/.env!")
    if not settings.SECRETS_ENCRYPTION_KEY:
        log.warning("SECRETS_ENCRYPTION_KEY is empty — encrypted SQL sessions cannot be persisted")

    await init_db()
    await acquire_instance_lock()
    task = None
    try:
        await load_runtime_settings()
        try:
            migrated_secrets = await secrets_store.migrate_legacy_to_db()
            if migrated_secrets:
                log.info("Migrated %d legacy encrypted secret(s) into SQL", migrated_secrets)
            loaded_api = await secrets_store.load_telegram_api_config()
            if loaded_api:
                log.info("Loaded encrypted Telegram API configuration from SQL")
        except Exception as exc:
            log.warning("Encrypted runtime secret loading skipped: %s", exc)
        recovered = await recover_interrupted_jobs()
        if recovered:
            log.warning("Marked %d unfinished bulk job(s) as interrupted", recovered)
        manager.set_loop(asyncio.get_event_loop())
        await manager.startup_load_all()
        await phone_check_runner.start()

        async def status_loop():
            while True:
                try:
                    await manager.refresh_status_all()
                    await manager.cleanup_pending()
                    await cleanup_auth_state()
                    await recover_interrupted_jobs()
                except Exception as e:
                    log.warning("status refresh: %s", e)
                await asyncio.sleep(30)

        task = asyncio.create_task(status_loop())
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await phone_check_runner.stop()
        await manager.shutdown()
        await release_instance_lock()


app = FastAPI(title="Multi TG Manager", lifespan=lifespan)

app.add_middleware(BrowserSecurityMiddleware)

cors_origins = [o.strip() for o in (settings.ALLOWED_ORIGIN or "").split(",") if o.strip()]
if os.environ.get("NODE_ENV", "").strip().lower() != "production":
    cors_origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(cors_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# auth endpoints (public)
app.include_router(auth_router)


@app.get("/api/health/live")
async def health_live():
    return {"ok": True}


@app.get("/api/health/ready")
async def health_ready():
    out = await readiness()
    return JSONResponse(out, status_code=200 if out.get("ok") else 503)


@app.get("/api/health")
async def health():
    out = await readiness()
    db_kind = "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"
    out.update({
        "database_kind": db_kind,
        "persistent_database": db_kind == "postgresql",
        "clients": len(manager._clients),
    })
    return out


# all data routers require auth
PROTECTED_DEPS = [Depends(require_auth)]
app.include_router(accounts.router,        dependencies=PROTECTED_DEPS)
app.include_router(profile.router,         dependencies=PROTECTED_DEPS)
app.include_router(security.router,        dependencies=PROTECTED_DEPS)
app.include_router(groups.router,          dependencies=PROTECTED_DEPS)
app.include_router(messaging.router,       dependencies=PROTECTED_DEPS)
app.include_router(inbox.router,           dependencies=PROTECTED_DEPS)
app.include_router(proxies.router,         dependencies=PROTECTED_DEPS)
app.include_router(phone_checks.router,     dependencies=PROTECTED_DEPS)
app.include_router(settings_router.router, dependencies=PROTECTED_DEPS)
app.include_router(bulk.router,            dependencies=PROTECTED_DEPS)
app.include_router(jobs.router,            dependencies=PROTECTED_DEPS)
app.include_router(audit.router,           dependencies=PROTECTED_DEPS)
app.include_router(system.router,          dependencies=PROTECTED_DEPS)


# Any /api/* path that didn't match a real route above returns a clean JSON 404
# for ANY method. Registered before the GET-only SPA fallback so an unmatched
# POST/PUT/DELETE (e.g. calling a new endpoint against a stale server) surfaces a
# proper "Not Found" instead of a confusing "405 Method Not Allowed".
@app.api_route(
    "/api/{rest:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
async def api_not_found(rest: str):
    return JSONResponse({"detail": "Not Found"}, status_code=404)


# ---- serve built frontend (single-port mode) ----
# `start.bat` builds the frontend into backend/static/. If that folder exists, serve it.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request):
        # never intercept the api
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # try a real file first (favicon, etc.)
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return JSONResponse({"detail": "Frontend not built. Run start.bat."}, status_code=503)
else:
    @app.get("/")
    async def no_static():
        return JSONResponse(
            {"detail": "Frontend not built. Run `npm run build` in frontend/ or use start.bat."},
            status_code=503,
        )
