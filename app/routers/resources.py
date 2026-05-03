import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from app.models import ResourceCreate, ResourceUpdate
from app.storage.markdown_store import resources_store
from app.auth import require_manager, require_admin
from app.services.logger_service import log_user_action
from app.services.scheduler_service import schedule_resource, unschedule_resource, run_resource

RESOURCE_REPORTS_DIR = Path("data/resource_reports")

logger = logging.getLogger(__name__)
router = APIRouter()


def _clean(item: dict) -> dict:
    item.pop("_body", None)
    return item


@router.get("/")
def list_resources():
    return [_clean(r) for r in resources_store.list()]


@router.get("/{resource_id}")
def get_resource(resource_id: str):
    item = resources_store.get(resource_id)
    if not item:
        raise HTTPException(404, "Resource not found")
    body = item.pop("_body", "")
    return {**item, "body": body}


@router.post("/", status_code=201)
def create_resource(data: ResourceCreate, _u=Depends(require_manager)):
    payload = data.model_dump()
    body = payload.pop("prompt", "")
    item = resources_store.create(payload, body)
    schedule_resource(item)
    log_user_action(logger, "Created resource: %s", item["name"])
    item.pop("_body", None)
    return item


@router.put("/{resource_id}")
def update_resource(resource_id: str, data: ResourceUpdate, _u=Depends(require_manager)):
    if not resources_store.get(resource_id):
        raise HTTPException(404, "Resource not found")
    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    body = payload.pop("prompt", None)
    updated = resources_store.update(resource_id, payload, body)
    schedule_resource(updated)
    log_user_action(logger, "Updated resource: %s", resource_id)
    updated.pop("_body", None)
    return updated


@router.delete("/{resource_id}", status_code=204)
def delete_resource(resource_id: str, _u=Depends(require_manager)):
    if not resources_store.delete(resource_id):
        raise HTTPException(404, "Resource not found")
    unschedule_resource(resource_id)
    log_user_action(logger, "Deleted resource: %s", resource_id)


@router.post("/{resource_id}/run")
async def manual_run(resource_id: str, _u=Depends(require_manager)):
    item = resources_store.get(resource_id)
    if not item:
        raise HTTPException(404, "Resource not found")
    log_user_action(logger, "Manual run triggered for resource: %s", resource_id)
    result = await run_resource(resource_id, manual=True)
    return result


@router.get("/{resource_id}/reports")
def get_reports(resource_id: str):
    from app.services.output_service import list_resource_reports
    return list_resource_reports(resource_id)


@router.get("/{resource_id}/reports/{filename}")
async def get_report(resource_id: str, filename: str):
    from app.services.output_service import read_resource_report
    content = await read_resource_report(resource_id, filename)
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


@router.delete("/{resource_id}/reports/{filename}", status_code=204)
def delete_report(resource_id: str, filename: str, _u=Depends(require_admin)):
    path = RESOURCE_REPORTS_DIR / resource_id / filename
    if not path.exists() or path.suffix != ".md":
        raise HTTPException(404, "Report not found")
    path.unlink()
    log_user_action(logger, "Deleted resource report: %s/%s", resource_id, filename)
