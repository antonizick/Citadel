import logging
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from app.models import SummaryReportCreate, SummaryReportUpdate
from app.storage.markdown_store import summary_reports_store
from app.services.scheduler_service import schedule_summary_report, unschedule_summary_report
from app.services.summary_service import run_summary_report
from app.auth import require_manager, require_admin
from app.services.logger_service import log_user_action

SUMMARY_FILES_DIR = Path("data/summary_reports")

logger = logging.getLogger(__name__)
router = APIRouter()
SUMMARY_REPORTS_DIR = Path("data/summary_reports")


def _clean(item: dict) -> dict:
    item.pop("_body", None)
    return item


@router.get("/")
def list_summary_reports():
    return [_clean(i) for i in summary_reports_store.list()]


@router.get("/{report_id}")
def get_summary_report(report_id: str):
    item = summary_reports_store.get(report_id)
    if not item:
        raise HTTPException(404, "Summary report not found")
    body = item.pop("_body", "")
    return {**item, "body": body}


@router.post("/", status_code=201)
def create_summary_report(data: SummaryReportCreate, _u=Depends(require_manager)):
    payload = data.model_dump()
    body = payload.pop("description", "")
    item = summary_reports_store.create(payload, body)
    schedule_summary_report(item)
    log_user_action(logger, "Created summary report: %s", item["name"])
    item.pop("_body", None)
    return item


@router.put("/{report_id}")
def update_summary_report(report_id: str, data: SummaryReportUpdate, _u=Depends(require_manager)):
    existing = summary_reports_store.get(report_id)
    if not existing:
        raise HTTPException(404, "Summary report not found")
    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    body = payload.pop("description", None)
    updated = summary_reports_store.update(report_id, payload, body)
    schedule_summary_report(updated)
    log_user_action(logger, "Updated summary report: %s", report_id)
    updated.pop("_body", None)
    return updated


@router.delete("/{report_id}", status_code=204)
def delete_summary_report(report_id: str, _u=Depends(require_manager)):
    if not summary_reports_store.delete(report_id):
        raise HTTPException(404, "Summary report not found")
    unschedule_summary_report(report_id)
    log_user_action(logger, "Deleted summary report: %s", report_id)


@router.post("/{report_id}/run")
async def manual_run(report_id: str, _u=Depends(require_manager)):
    item = summary_reports_store.get(report_id)
    if not item:
        raise HTTPException(404, "Summary report not found")
    log_user_action(logger, "Manual run triggered for summary report: %s", report_id)
    result = await run_summary_report(report_id, manual=True)
    return result


@router.get("/{report_id}/reports")
def get_reports(report_id: str):
    from app.services.output_service import list_summary_report_files
    return list_summary_report_files(report_id)


@router.get("/{report_id}/reports/{filename}")
async def get_report(report_id: str, filename: str):
    from app.services.output_service import read_summary_report_file
    content = await read_summary_report_file(report_id, filename)
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


@router.delete("/{report_id}/reports/{filename}", status_code=204)
def delete_report(report_id: str, filename: str, _u=Depends(require_admin)):
    path = SUMMARY_FILES_DIR / report_id / filename
    if not path.exists() or path.suffix != ".md":
        raise HTTPException(404, "Report not found")
    path.unlink()
    log_user_action(logger, "Deleted summary report file: %s/%s", report_id, filename)
