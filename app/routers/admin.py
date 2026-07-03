import asyncio
import io
import json
import logging
import random
import shutil
import string
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from app.auth import require_admin, clear_all_sessions, COOKIE_NAME
from app.config import get_config, save_config
from app.services.logger_service import log_user_action

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_admin)])

DATA_DIR = Path("data")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _zip_dir(source: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(source.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(source))
    buf.seek(0)
    return buf.read()


def _zip_iocs() -> bytes:
    """Zip the IOC SQLite DB + IOC source config into one archive rooted at data/."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = DATA_DIR / "iocs.db"
        if db_path.exists():
            zf.write(db_path, db_path.relative_to(DATA_DIR))
        for name in ("ioc_sources.yaml", "ioc_sync_status.yaml"):
            cfg = DATA_DIR / "config" / name
            if cfg.exists():
                zf.write(cfg, cfg.relative_to(DATA_DIR))
    buf.seek(0)
    return buf.read()


def _zip_response(data: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _safe_extract(content: bytes, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve()
    count = 0
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for member in zf.namelist():
            dest = (target / member).resolve()
            if not str(dest).startswith(str(resolved)):
                raise HTTPException(400, f"Unsafe path in archive: {member}")
            zf.extract(member, target)
            count += 1
    return count


# ── Exports ──────────────────────────────────────────────────────────────────

@router.get("/backup/full")
def backup_full():
    """ZIP the entire data/ directory — config, interests, resources, reports, resource_reports,
    summary_reports, IOC data, IOC source config, users, and all other data files."""
    if not DATA_DIR.exists():
        raise HTTPException(404, "Data directory not found")
    data = _zip_dir(DATA_DIR)
    log_user_action(logger, "Full system backup exported")
    return _zip_response(data, f"nxcitadel_full_{_timestamp()}.zip")


@router.get("/backup/settings")
def backup_settings():
    path = DATA_DIR / "config" / "settings.yaml"
    if not path.exists():
        raise HTTPException(404, "Settings file not found")
    log_user_action(logger, "Settings exported")
    return StreamingResponse(
        io.BytesIO(path.read_bytes()),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="nxcitadel_settings_{_timestamp()}.yaml"'},
    )


@router.get("/backup/interests")
def backup_interests():
    d = DATA_DIR / "interests"
    if not d.exists():
        raise HTTPException(404, "Interests directory not found")
    log_user_action(logger, "Interests exported")
    return _zip_response(_zip_dir(d), f"nxcitadel_interests_{_timestamp()}.zip")


@router.get("/backup/resources")
def backup_resources():
    d = DATA_DIR / "resources"
    if not d.exists():
        raise HTTPException(404, "Resources directory not found")
    log_user_action(logger, "Trusted resources exported")
    return _zip_response(_zip_dir(d), f"nxcitadel_resources_{_timestamp()}.zip")


@router.get("/backup/reports")
def backup_reports():
    d = DATA_DIR / "reports"
    if not d.exists():
        raise HTTPException(404, "Reports directory not found")
    log_user_action(logger, "Reports exported")
    return _zip_response(_zip_dir(d), f"nxcitadel_reports_{_timestamp()}.zip")


@router.get("/backup/iocs")
def backup_iocs():
    db_path = DATA_DIR / "iocs.db"
    if not db_path.exists():
        raise HTTPException(404, "IOC database not found — run a pull first")
    data = _zip_iocs()
    log_user_action(logger, "IOC data exported")
    return _zip_response(data, f"nxcitadel_iocs_{_timestamp()}.zip")


@router.get("/backup/users")
def backup_users():
    d = DATA_DIR / "users"
    if not d.exists():
        raise HTTPException(404, "Users directory not found")
    log_user_action(logger, "Users exported")
    return _zip_response(_zip_dir(d), f"nxcitadel_users_{_timestamp()}.zip")


# ── Restores ─────────────────────────────────────────────────────────────────

_FULL_RESTORE_DIRS = [
    "interests", "resources", "reports", "resource_reports",
    "summary_reports", "config", "users",
]


@router.post("/restore/full")
async def restore_full(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()

    # Validate the ZIP is readable before wiping anything
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
        if not names:
            raise HTTPException(400, "The uploaded ZIP is empty")
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file — aborting restore")

    # Clean-wipe known data subdirectories so the restore reflects the exact
    # backup state (no stale files from after the backup survive).
    for subdir in _FULL_RESTORE_DIRS:
        path = DATA_DIR / subdir
        if path.exists():
            shutil.rmtree(path)
    db_path = DATA_DIR / "iocs.db"
    if db_path.exists():
        db_path.unlink()

    count = _safe_extract(content, DATA_DIR)
    log_user_action(logger, "Full system restore applied — clean wipe + restore (%d files)", count)
    return {"ok": True, "message": f"Restored {count} files — reload the app to reflect changes"}


@router.post("/restore/settings")
async def restore_settings(file: UploadFile = File(...)):
    if not (file.filename.endswith(".yaml") or file.filename.endswith(".yml")):
        raise HTTPException(400, "Expected a .yaml file")
    content = await file.read()
    path = DATA_DIR / "config" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    log_user_action(logger, "Settings restored from upload")
    return {"ok": True, "message": "Settings restored — reload Settings page to verify"}


@router.post("/restore/interests")
async def restore_interests(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()
    count = _safe_extract(content, DATA_DIR / "interests")
    log_user_action(logger, "Interests restored (%d files)", count)
    return {"ok": True, "message": f"Restored {count} interest files"}


@router.post("/restore/resources")
async def restore_resources(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()
    count = _safe_extract(content, DATA_DIR / "resources")
    log_user_action(logger, "Trusted resources restored (%d files)", count)
    return {"ok": True, "message": f"Restored {count} resource files"}


@router.post("/restore/reports")
async def restore_reports(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()
    count = _safe_extract(content, DATA_DIR / "reports")
    log_user_action(logger, "Reports restored (%d files)", count)
    return {"ok": True, "message": f"Restored {count} report files"}


@router.post("/restore/iocs")
async def restore_iocs(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()
    count = _safe_extract(content, DATA_DIR)
    log_user_action(logger, "IOC data restored (%d files)", count)
    return {"ok": True, "message": f"Restored {count} IOC files — IOC pages will reflect the restored data immediately"}


@router.post("/restore/users")
async def restore_users(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")
    content = await file.read()
    count = _safe_extract(content, DATA_DIR / "users")
    log_user_action(logger, "Users restored (%d files)", count)
    return {"ok": True, "message": f"Restored {count} user files — reload to reflect changes"}


# ── Build Package ─────────────────────────────────────────────────────────────

_SKIP_TOP = {"data", "logs", ".venv", ".claude", ".git"}
_SKIP_NAMES = {"__pycache__", ".citadel.pid"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}


def _package_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = info.name
    if name == ".":
        return info
    if name.startswith("./"):
        name = name[2:]

    p = Path(name)
    parts = p.parts

    if not parts:
        return info

    top = parts[0]

    if top in _SKIP_TOP:
        return None
    if top in _SKIP_NAMES or p.name in _SKIP_NAMES:
        return None
    if "__pycache__" in parts:
        return None
    if p.suffix in _SKIP_SUFFIXES:
        return None
    if top == "deploy" and len(parts) >= 2 and (parts[1].endswith(".tar.gz") or parts[1].endswith(".zip")):
        return None
    if top == "deploy" and len(parts) >= 2 and parts[1] == "archived":
        return None

    return info


def _expected_source_files(root: Path) -> set[str]:
    """Enumerate every file that SHOULD appear in the package — mirrors _package_filter logic."""
    result = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        if not parts:
            continue
        top = parts[0]
        if top in _SKIP_TOP:
            continue
        if top in _SKIP_NAMES or p.name in _SKIP_NAMES:
            continue
        if "__pycache__" in parts:
            continue
        if p.suffix in _SKIP_SUFFIXES:
            continue
        if top == "deploy" and len(parts) >= 2 and (parts[1].endswith(".tar.gz") or parts[1].endswith(".zip")):
            continue
        if top == "deploy" and len(parts) >= 2 and parts[1] == "archived":
            continue
        result.add(str(rel))
    return result


def _verify_package(pkg_path: Path, root: Path) -> list[str]:
    """Return sorted list of source files absent from the built archive."""
    expected = _expected_source_files(root)
    with tarfile.open(str(pkg_path), "r:gz") as tf:
        packaged = {n.lstrip("./") for n in tf.getnames()}
    return sorted(expected - packaged)


@router.post("/build-package")
def build_package():
    root = Path(".").resolve()
    deploy_dir = root / "deploy"
    deploy_dir.mkdir(exist_ok=True)

    ts = _timestamp()
    archive_dir = deploy_dir / "archived"
    archive_dir.mkdir(exist_ok=True)
    timestamped_path = archive_dir / f"nxcitadel-{ts}.tar.gz"
    latest_path = deploy_dir / "nxcitadel-latest.tar.gz"

    try:
        with tarfile.open(str(timestamped_path), "w:gz") as tf:
            tf.add(root, arcname=".", filter=_package_filter)
        shutil.copy2(str(timestamped_path), str(latest_path))
    except Exception as e:
        logger.error("Build package failed: %s", e)
        raise HTTPException(500, f"Build failed: {e}")

    size_kb = timestamped_path.stat().st_size // 1024

    # Post-build integrity check: confirm every expected source file is present
    missing = _verify_package(timestamped_path, root)
    if missing:
        logger.error("Build package integrity check FAILED — %d file(s) missing: %s", len(missing), missing)
        timestamped_path.unlink(missing_ok=True)
        latest_path.unlink(missing_ok=True)
        raise HTTPException(500, {
            "error": f"Package integrity check failed — {len(missing)} file(s) missing from archive",
            "missing": missing,
        })

    log_user_action(logger, "Build package created: %s (%d KB)", timestamped_path.name, size_kb)
    return {
        "ok": True,
        "timestamped": f"archived/{timestamped_path.name}",
        "latest": latest_path.name,
        "size_kb": size_kb,
        "message": f"Package built and verified: {timestamped_path.name} ({size_kb} KB)",
    }


@router.get("/download-package")
def download_package():
    """Stream the latest built deployment package as a direct download."""
    latest = Path("deploy") / "nxcitadel-latest.tar.gz"
    if not latest.exists():
        raise HTTPException(404, "No package found — use Build Package first")
    size_kb = latest.stat().st_size // 1024
    log_user_action(logger, "Deployment package downloaded (%d KB)", size_kb)
    return StreamingResponse(
        open(latest, "rb"),
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="nxcitadel-latest.tar.gz"'},
    )


_DEFAULT_UPDATE_URL = "https://www.antonizick.com/nxcitadel/nxcitadel-latest.tar.gz"


@router.get("/self-update/stream")
async def self_update_stream(url: str = Query(default=_DEFAULT_UPDATE_URL)):
    """SSE stream that backs up, snapshots, downloads a package, installs it, and restarts."""

    async def generate():
        loop = asyncio.get_event_loop()

        def evt(step, status: str, msg: str) -> str:
            return f"data: {json.dumps({'step': step, 'status': status, 'msg': msg})}\n\n"

        # ── Step 1: Full data backup ──────────────────────────────────────────
        yield evt(1, "running", "Starting full system backup…")
        try:
            if not DATA_DIR.exists():
                yield evt(1, "warn", "No data/ directory found — skipping backup")
            else:
                data_bytes = await loop.run_in_executor(None, lambda: _zip_dir(DATA_DIR))
                ts = _timestamp()
                deploy_dir = Path("deploy")
                deploy_dir.mkdir(exist_ok=True)
                backup_path = deploy_dir / f"nxcitadel_autobackup_{ts}.zip"
                backup_path.write_bytes(data_bytes)
                size_mb = len(data_bytes) / (1024 * 1024)
                log_user_action(logger, "Self-update: auto backup saved to %s (%.1f MB)", backup_path.name, size_mb)
                yield evt(1, "done", f"Backup saved → deploy/{backup_path.name} ({size_mb:.1f} MB)")
        except Exception as e:
            yield evt(1, "error", f"Backup failed: {e}")
            return

        await asyncio.sleep(0.05)

        # ── Step 2: Build deployment package (code snapshot) ─────────────────
        yield evt(2, "running", "Snapshotting current code into a deployment package…")
        try:
            root = Path(".").resolve()
            deploy_dir = root / "deploy"
            deploy_dir.mkdir(exist_ok=True)
            archive_dir = deploy_dir / "archived"
            archive_dir.mkdir(exist_ok=True)
            ts = _timestamp()
            pkg_path = archive_dir / f"nxcitadel-{ts}.tar.gz"
            latest_path = deploy_dir / "nxcitadel-latest.tar.gz"

            def _build():
                with tarfile.open(str(pkg_path), "w:gz") as tf:
                    tf.add(root, arcname=".", filter=_package_filter)
                shutil.copy2(str(pkg_path), str(latest_path))
                return pkg_path.stat().st_size // 1024

            size_kb = await loop.run_in_executor(None, _build)
            log_user_action(logger, "Self-update: snapshot built %s (%d KB)", pkg_path.name, size_kb)
            yield evt(2, "done", f"Snapshot built → deploy/archived/{pkg_path.name} ({size_kb} KB)")
        except Exception as e:
            yield evt(2, "error", f"Snapshot build failed: {e}")
            return

        await asyncio.sleep(0.05)

        # ── Step 3: Download, extract, install ───────────────────────────────
        yield evt(3, "running", f"Downloading package from: {url}")
        tmpdir_path = None
        try:
            tmpdir_path = Path(tempfile.mkdtemp(prefix="nxcitadel-update-"))
            pkg_file = tmpdir_path / "update.tar.gz"

            def _download():
                result = subprocess.run(
                    ["curl", "--fail", "--show-error", "--location", "--silent",
                     "--output", str(pkg_file), url],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"curl exit {result.returncode}")
                return pkg_file.stat().st_size // 1024

            dl_kb = await loop.run_in_executor(None, _download)
            yield evt(3, "done", f"Downloaded ({dl_kb} KB)")

            await asyncio.sleep(0.05)
            yield evt(3, "running", "Extracting package…")

            extract_dir = tmpdir_path / "src"
            extract_dir.mkdir()

            def _extract():
                with tarfile.open(str(pkg_file), "r:gz") as tf:
                    tf.extractall(str(extract_dir))

            await loop.run_in_executor(None, _extract)
            yield evt(3, "done", "Package extracted")

            await asyncio.sleep(0.05)
            yield evt(3, "running", "Installing core system files (data and config preserved)…")

            root_str = str(Path(".").resolve())

            def _rsync():
                result = subprocess.run(
                    ["rsync", "-a", "--delete", "--force",
                     "--exclude=data/",
                     "--exclude=logs/",
                     "--exclude=.venv/",
                     "--exclude=__pycache__/",
                     "--exclude=*.pyc",
                     "--exclude=*.pyo",
                     "--exclude=deploy/nxcitadel-latest.tar.gz",
                     "--exclude=deploy/archived/",
                     "--exclude=deploy/nxcitadel_autobackup_*.zip",
                     str(extract_dir) + "/", root_str + "/"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"rsync exit {result.returncode}")

            await loop.run_in_executor(None, _rsync)
            log_user_action(logger, "Self-update: core files installed from %s", url)
            yield evt(3, "done", "Core system files updated — data and configuration preserved")

        except Exception as e:
            yield evt(3, "error", f"File update failed: {e}")
            return
        finally:
            if tmpdir_path:
                await loop.run_in_executor(
                    None, lambda: shutil.rmtree(str(tmpdir_path), ignore_errors=True)
                )

        await asyncio.sleep(0.05)

        # ── Step 4: pip install + schedule restart ────────────────────────────
        yield evt(4, "running", "Updating Python dependencies…")
        venv_pip = Path(".venv/bin/pip")
        if venv_pip.exists():
            def _pip():
                result = subprocess.run(
                    [str(venv_pip), "install", "--quiet", "--upgrade",
                     "-r", "requirements.txt"],
                    capture_output=True, text=True, timeout=300,
                )
                return result.returncode, (result.stderr or "").strip()[:400]

            rc, pip_err = await loop.run_in_executor(None, _pip)
            if rc != 0 and pip_err:
                yield evt(4, "warn", f"pip warnings: {pip_err}")
            else:
                yield evt(4, "done", "Python dependencies up to date")
        else:
            yield evt(4, "warn", "Virtual environment not found — skipping dependency update")

        await asyncio.sleep(0.05)

        # Check whether systemctl is available before scheduling a restart
        systemctl = shutil.which("systemctl")
        if systemctl:
            yield evt(4, "running", "Scheduling service restart in 8 seconds…")
            subprocess.Popen(
                ["bash", "-c", f"sleep 8 && sudo {systemctl} restart nxcitadel"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log_user_action(logger, "Self-update: service restart scheduled via systemctl")
            yield evt(4, "done", "Restart scheduled — Citadel will reload in ~8 seconds")
        else:
            yield evt(4, "warn", "systemctl not found — restart Citadel manually to apply the update")

        await asyncio.sleep(0.1)
        yield evt("complete", "done",
                  "Self-update complete! Citadel is restarting. This page will auto-reload.")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Factory Reset ─────────────────────────────────────────────────────────────

_reset_challenge: dict = {}   # {"code": str, "expires": datetime}
_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_TTL_MINUTES = 10


def _new_code() -> str:
    return "".join(random.choices(_CODE_CHARS, k=8))


@router.post("/factory-reset/challenge")
def factory_reset_challenge():
    """Generate a one-time validation code the user must repeat to confirm the reset."""
    code = _new_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    _reset_challenge["code"] = code
    _reset_challenge["expires"] = expires
    logger.warning("Factory reset challenge issued (expires in %d min)", _CODE_TTL_MINUTES)
    return {"code": code, "expires_in_minutes": _CODE_TTL_MINUTES}


@router.post("/factory-reset/confirm")
def factory_reset_confirm(payload: dict):
    submitted = payload.get("code", "").strip().upper()

    if not _reset_challenge.get("code"):
        raise HTTPException(400, "No active challenge — request a new code first")

    if datetime.now(timezone.utc) > _reset_challenge["expires"]:
        _reset_challenge.clear()
        raise HTTPException(400, "Challenge code has expired — request a new one")

    if submitted != _reset_challenge["code"]:
        raise HTTPException(400, "Incorrect code — factory reset aborted")

    _reset_challenge.clear()

    # Wipe every user-data directory back to factory state
    _wipe_targets = [
        "interests", "resources", "reports", "resource_reports",
        "summary_reports", "iocs", "config", "users",
    ]
    wiped: list[str] = []
    for target in _wipe_targets:
        path = DATA_DIR / target
        if path.exists():
            shutil.rmtree(path)
            wiped.append(target)
        path.mkdir(parents=True, exist_ok=True)

    db_path = DATA_DIR / "iocs.db"
    if db_path.exists():
        db_path.unlink()
        wiped.append("iocs.db")

    # Recreate expected subdirs
    (DATA_DIR / "logs" / "archive").mkdir(parents=True, exist_ok=True)

    # Cancel all user-created scheduler jobs (interest/resource/summary) so the
    # dashboard shows no upcoming runs after the reset.
    from app.services.scheduler_service import clear_user_schedules
    jobs_cleared = clear_user_schedules()

    # Invalidate every active session so all users must re-authenticate.
    clear_all_sessions()

    # Re-seed the default admin account so the system is immediately accessible
    from app.storage.user_store import users_store
    from app.auth import hash_password
    users_store.create({
        "username": "admin",
        "password_hash": hash_password("admin"),
        "role": "admin",
        "mfa_enabled": False,
        "mfa_secret": "",
        "mfa_exempt": True,
    })

    logger.warning("FACTORY RESET performed — wiped: %s; %d scheduled jobs cleared; default admin/admin re-seeded", wiped, jobs_cleared)
    return {
        "ok": True,
        "message": (
            "Factory reset complete. All data has been wiped and the system has been returned to "
            "its original state. Default login restored: admin / admin — "
            "change this password immediately. Reload the app."
        ),
    }


@router.post("/terminate-sessions")
def terminate_sessions(request: Request, _u=Depends(require_admin)):
    """Immediately invalidate every active session except the caller's own."""
    caller_token = request.cookies.get(COOKIE_NAME)
    cleared = clear_all_sessions(except_token=caller_token)
    log_user_action(logger, "Terminated all active sessions (%d cleared)", cleared)
    return {"ok": True, "cleared": cleared, "message": f"{cleared} session(s) terminated — all other users have been logged out."}


@router.get("/system-state")
def get_system_state():
    return {"system_state": get_config().system_state}


@router.put("/system-state")
def set_system_state(payload: dict):
    cfg = get_config()
    cfg.system_state = payload.get("system_state", "").strip()
    save_config(cfg)
    log_user_action(logger, "System state set to: %s", cfg.system_state or "(empty)")
    return {"ok": True, "system_state": cfg.system_state}


@router.get("/default-resource-prompt")
def get_default_resource_prompt():
    return {"default_resource_prompt": get_config().default_resource_prompt}


@router.put("/default-resource-prompt")
def set_default_resource_prompt(payload: dict):
    cfg = get_config()
    cfg.default_resource_prompt = payload.get("default_resource_prompt", "").strip()
    save_config(cfg)
    log_user_action(logger, "Default resource prompt updated (%d chars)", len(cfg.default_resource_prompt))
    return {"ok": True, "default_resource_prompt": cfg.default_resource_prompt}
