import logging
import gzip
import os
import shutil
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta

LOG_DIR = Path("logs")

# Custom level sitting just above INFO so it appears wherever INFO does
USER_ACTION = 21
logging.addLevelName(USER_ACTION, "INFO USER")


def log_user_action(logger_instance: logging.Logger, msg: str, *args) -> None:
    """Log a user-initiated action at the INFO USER level."""
    logger_instance.log(USER_ACTION, msg, *args)
ARCHIVE_DIR = LOG_DIR / "archive"
LOG_FILE = LOG_DIR / "citadel.log"
ARCHIVE_AFTER_DAYS = 7


def _namer(default_name: str) -> str:
    return default_name + ".gz"


def _rotator(source: str, dest: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now().strftime("%Y-%m")
    month_dir = ARCHIVE_DIR / date_part
    month_dir.mkdir(parents=True, exist_ok=True)
    final_path = month_dir / (Path(dest).name)
    with open(source, "rb") as f_in:
        with gzip.open(str(final_path), "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File with monthly rotation (every 30 days) → gzip archive
    fh = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=30,
        backupCount=0,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    fh.rotator = _rotator
    fh.namer = _namer
    root.addHandler(fh)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def read_log_lines(lines: int = 500) -> list[str]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, encoding="utf-8") as f:
        all_lines = f.readlines()
    return [l.rstrip() for l in all_lines[-lines:]]


def list_archives() -> list[dict]:
    if not ARCHIVE_DIR.exists():
        return []
    result = []
    for gz in sorted(ARCHIVE_DIR.rglob("*.gz"), reverse=True):
        result.append({"path": str(gz.relative_to(ARCHIVE_DIR)), "size": gz.stat().st_size})
    return result
