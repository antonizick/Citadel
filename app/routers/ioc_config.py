"""IOC source configuration, sync status, and manual pull endpoints."""
import logging
from fastapi import APIRouter, Depends
from app.ioc_config import get_ioc_config, save_ioc_config, IocSourcesSettings
from app.ioc_sync_status import load_sync_status
from app.auth import require_admin, require_manager
from app.services.logger_service import log_user_action

logger = logging.getLogger(__name__)
router = APIRouter()

_MASK_SENTINEL = "••••"


def _mask_config(data: dict) -> dict:
    for src in data:
        key = data[src].get("api_key", "")
        if key:
            data[src]["api_key"] = _MASK_SENTINEL + key[-4:]
    return data


# ── Static routes first ───────────────────────────────────────────────────────

@router.get("/status")
def get_sync_status(_u=Depends(require_manager)):
    return load_sync_status()


@router.post("/pull")
async def manual_pull(_u=Depends(require_manager)):
    from app.services.ioc_collector import run_all_collections
    from app.services.scheduler_service import get_scheduler
    job = get_scheduler().get_job("ioc_collection")
    next_iso = job.next_run_time.isoformat() if job and job.next_run_time else None
    results = await run_all_collections(next_run_iso=next_iso)
    log_user_action(logger, "Manual IOC pull triggered: %s", results)
    total = sum(r.get("count", 0) for r in results.values() if isinstance(r, dict))
    return {"ok": True, "total": total, "results": results}


# ── Config CRUD ───────────────────────────────────────────────────────────────

@router.get("/")
def read_ioc_config(_u=Depends(require_admin)):
    raw = get_ioc_config().model_dump()
    return _mask_config(raw)


@router.put("/")
def update_ioc_config(new_cfg: IocSourcesSettings, _u=Depends(require_admin)):
    current = get_ioc_config()
    data = new_cfg.model_dump()
    for src in data:
        key = data[src].get("api_key", "")
        if key.startswith(_MASK_SENTINEL):
            data[src]["api_key"] = getattr(current, src).api_key
    merged = IocSourcesSettings(**data)
    save_ioc_config(merged)
    log_user_action(logger, "IOC source configuration updated")
    return {"ok": True}
