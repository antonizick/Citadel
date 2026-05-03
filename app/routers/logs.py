from fastapi import APIRouter, Query
from app.services.logger_service import read_log_lines, list_archives

router = APIRouter()


@router.get("/")
def get_logs(lines: int = Query(default=200, le=2000)):
    return {"lines": read_log_lines(lines)}


@router.get("/archives")
def get_archives():
    return list_archives()
