import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from app.models import InterestCreate, InterestUpdate
from app.storage.markdown_store import interests_store
from app.services.scheduler_service import schedule_interest, unschedule_interest, run_interest
from app.auth import require_manager, require_admin
from app.services.logger_service import log_user_action
from app.services.output_service import _ts_from_filename

logger = logging.getLogger(__name__)
router = APIRouter()
REPORTS_DIR = Path("data/reports")


def _clean(item: dict) -> dict:
    item.pop("_body", None)
    return item


@router.get("/")
def list_interests():
    return [_clean(i) for i in interests_store.list()]


# Static routes MUST come before /{interest_id} to avoid being swallowed as a path param
@router.get("/activity/recent")
def recent_activity(limit: int = 20):
    """Return the most recent reports across all interests, for the dashboard feed."""
    interest_names = {i["id"]: i.get("name", "Unknown") for i in interests_store.list()}
    entries = []
    if REPORTS_DIR.exists():
        for interest_dir in REPORTS_DIR.iterdir():
            if not interest_dir.is_dir():
                continue
            name = interest_names.get(interest_dir.name, "Unknown")
            for report_file in interest_dir.glob("*.md"):
                entries.append({
                    "interest_id": interest_dir.name,
                    "interest_name": name,
                    "filename": report_file.name,
                    "ran_at": _ts_from_filename(report_file).isoformat(),
                    "size": report_file.stat().st_size,
                })
    entries.sort(key=lambda x: x["ran_at"], reverse=True)
    return entries[:limit]


@router.get("/reports/count-24h")
def reports_count_24h():
    """Count report files written in the last 24 hours across all interests."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    count = 0
    if REPORTS_DIR.exists():
        for report_file in REPORTS_DIR.rglob("*.md"):
            if _ts_from_filename(report_file) >= cutoff:
                count += 1
    return {"count": count}


@router.get("/{interest_id}")
def get_interest(interest_id: str):
    item = interests_store.get(interest_id)
    if not item:
        raise HTTPException(404, "Interest not found")
    body = item.pop("_body", "")
    return {**item, "body": body}


@router.post("/", status_code=201)
def create_interest(data: InterestCreate, _u=Depends(require_manager)):
    payload = data.model_dump()
    body = payload.pop("description", "")
    item = interests_store.create(payload, body)
    schedule_interest(item)
    log_user_action(logger, "Created interest: %s", item["name"])
    item.pop("_body", None)
    return item


@router.put("/{interest_id}")
def update_interest(interest_id: str, data: InterestUpdate, _u=Depends(require_manager)):
    existing = interests_store.get(interest_id)
    if not existing:
        raise HTTPException(404, "Interest not found")
    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    body = payload.pop("description", None)
    updated = interests_store.update(interest_id, payload, body)
    schedule_interest(updated)
    log_user_action(logger, "Updated interest: %s", interest_id)
    updated.pop("_body", None)
    return updated


@router.delete("/{interest_id}", status_code=204)
def delete_interest(interest_id: str, _u=Depends(require_manager)):
    if not interests_store.delete(interest_id):
        raise HTTPException(404, "Interest not found")
    unschedule_interest(interest_id)
    log_user_action(logger, "Deleted interest: %s", interest_id)


@router.post("/{interest_id}/run")
async def manual_run(interest_id: str, _u=Depends(require_manager)):
    item = interests_store.get(interest_id)
    if not item:
        raise HTTPException(404, "Interest not found")
    log_user_action(logger, "Manual run triggered for: %s", interest_id)
    result = await run_interest(interest_id, manual=True)
    return result


@router.get("/{interest_id}/reports")
def get_reports(interest_id: str):
    from app.services.output_service import list_reports
    return list_reports(interest_id)


@router.get("/{interest_id}/reports/{filename}")
async def get_report(interest_id: str, filename: str):
    from app.services.output_service import read_report
    content = await read_report(interest_id, filename)
    if not content:
        raise HTTPException(404, "Report not found")
    generated_at = None
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[3:end]
            for line in frontmatter.splitlines():
                if line.startswith("generated_at:"):
                    generated_at = line.split(":", 1)[1].strip()
                    break
            content = content[end + 3:].lstrip("\n")
    return {"content": content, "generated_at": generated_at}


@router.delete("/{interest_id}/reports/{filename}", status_code=204)
def delete_report(interest_id: str, filename: str, _u=Depends(require_admin)):
    path = REPORTS_DIR / interest_id / filename
    if not path.exists() or path.suffix != ".md":
        raise HTTPException(404, "Report not found")
    path.unlink()
    log_user_action(logger, "Deleted report: %s/%s", interest_id, filename)
