"""Tracks IOC collection sync status — last run, next run, per-source results."""
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SYNC_STATUS_PATH = Path("data/config/ioc_sync_status.yaml")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sync_status() -> dict:
    if not SYNC_STATUS_PATH.exists():
        return {"last_run": None, "next_run": None, "sources": {}}
    with open(SYNC_STATUS_PATH) as f:
        return yaml.safe_load(f) or {"last_run": None, "next_run": None, "sources": {}}


def save_sync_status(status: dict) -> None:
    SYNC_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATUS_PATH, "w") as f:
        yaml.dump(status, f, default_flow_style=False)


def record_run_start(next_run_iso: Optional[str] = None) -> None:
    status = load_sync_status()
    status["last_run"] = _now()
    if next_run_iso:
        status["next_run"] = next_run_iso
    save_sync_status(status)


def record_source_result(source: str, count: int, error: Optional[str] = None) -> None:
    status = load_sync_status()
    status.setdefault("sources", {})[source] = {
        "last_run": _now(),
        "count": count,
        "error": error,
    }
    save_sync_status(status)
