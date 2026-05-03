import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.logger_service import setup_logging
from app.services.scheduler_service import SchedulerService
from app.routers import interests, resources, settings, logs, admin, summary_reports
from app.routers import auth_router, users, iocs, ioc_config

logger = logging.getLogger(__name__)

# Paths that bypass auth middleware
_AUTH_BYPASS = {"/login", "/health"}
_AUTH_BYPASS_PREFIXES = ("/static/", "/api/auth/")


def _seed_admin() -> None:
    from app.storage.user_store import users_store
    from app.auth import hash_password
    if not users_store.list():
        users_store.create({
            "username": "admin",
            "password_hash": hash_password("admin"),
            "role": "admin",
            "mfa_enabled": False,
            "mfa_secret": "",
            "mfa_exempt": True,
        })
        logger.info("Seeded default admin user: admin / admin  ← change this password and enable MFA immediately")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    _seed_admin()
    scheduler = SchedulerService()
    await scheduler.start()
    from app.services.scheduler_service import get_scheduler
    from app.storage.ioc_store import ioc_store as _ioc_store
    from app.services.ioc_collector import run_all_collections as _ioc_collect
    from apscheduler.triggers.cron import CronTrigger as _Cron
    _sched = get_scheduler()
    # IOC maintenance at 02:00 UTC daily
    _sched.add_job(
        lambda: _ioc_store.run_maintenance(),
        trigger=_Cron(hour=2, minute=0, timezone="UTC"),
        id="ioc_maintenance",
        replace_existing=True,
        name="IOC daily maintenance",
    )
    # IOC feed collection at 03:00 UTC daily
    _collect_trigger = _Cron(hour=3, minute=0, timezone="UTC")
    async def _scheduled_collect():
        job = _sched.get_job("ioc_collection")
        next_iso = job.next_run_time.isoformat() if job and job.next_run_time else None
        await _ioc_collect(next_run_iso=next_iso)
    _sched.add_job(
        _scheduled_collect,
        trigger=_collect_trigger,
        id="ioc_collection",
        replace_existing=True,
        name="IOC daily feed collection",
    )
    # Record next run time in status file on startup
    _collect_job = _sched.get_job("ioc_collection")
    if _collect_job and _collect_job.next_run_time:
        from app.ioc_sync_status import load_sync_status, save_sync_status
        _st = load_sync_status()
        _st["next_run"] = _collect_job.next_run_time.isoformat()
        save_sync_status(_st)
    app.state.scheduler = scheduler
    logger.info("Nx-Citadel started")
    yield
    await scheduler.stop()
    logger.info("Nx-Citadel stopped")


import time as _time
import json as _json
import os as _os
_STATIC_VER = str(int(_time.time()))  # changes on every server restart / redeploy
_version_file = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "version.json")
_APP_VERSION = _json.loads(open(_version_file).read()).get("version", "") if _os.path.exists(_version_file) else ""

app = FastAPI(title="Nx-Citadel", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_BYPASS or any(path.startswith(p) for p in _AUTH_BYPASS_PREFIXES):
        return await call_next(request)

    from app.auth import get_session, COOKIE_NAME
    token = request.cookies.get(COOKIE_NAME)
    session = get_session(token) if token else None

    if not session:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    request.state.user = session
    return await call_next(request)


# Routers — auth_router handles /login and /api/auth/* (no prefix)
app.include_router(auth_router.router)
app.include_router(interests.router,       prefix="/api/interests",        tags=["interests"])
app.include_router(resources.router,       prefix="/api/resources",        tags=["resources"])
app.include_router(summary_reports.router, prefix="/api/summary-reports",  tags=["summary-reports"])
app.include_router(settings.router,   prefix="/api/settings",   tags=["settings"])
app.include_router(logs.router,       prefix="/api/logs",       tags=["logs"])
app.include_router(admin.router,      prefix="/api/admin",      tags=["admin"])
app.include_router(users.router,      prefix="/api/users",      tags=["users"])
app.include_router(iocs.router,       prefix="/api/iocs",       tags=["iocs"])
app.include_router(ioc_config.router, prefix="/api/ioc-config", tags=["ioc-config"])


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "v": _STATIC_VER, "app_version": _APP_VERSION})


@app.get("/health")
def health():
    return {"status": "ok"}
