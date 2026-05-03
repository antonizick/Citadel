"""IOC CRUD API.

IMPORTANT: static paths (/counts, /maintenance/run) MUST be registered before
parameterized paths (/{ioc_type}) so Starlette doesn't swallow them.
Sub-path routes (/{ioc_type}/csv-template, /{ioc_type}/bulk-upload) must also
come before the bare /{ioc_type} and /{ioc_type}/{ioc_id} routes.
"""
import csv
import io
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.auth import get_current_user, require_manager
from app.services.logger_service import log_user_action
from app.storage.ioc_store import IOC_TYPES, ioc_store

logger = logging.getLogger(__name__)
router = APIRouter()
_VALID = set(IOC_TYPES)

# CSV column order per IOC type (value must be first)
_CSV_COLS: dict[str, list[str]] = {
    "ip": [
        "value", "status", "threat_type", "malware_family", "reporter",
        "first_seen", "tags", "sources", "refs",
        "port", "country", "asn", "asn_name", "hostname",
        "priority_override", "expires_at", "notes",
    ],
    "hash": [
        "value", "status", "threat_type", "malware_family", "reporter",
        "first_seen", "tags", "sources", "refs",
        "hash_md5", "hash_sha1", "file_type", "file_name",
        "priority_override", "expires_at", "notes",
    ],
    "url": [
        "value", "status", "threat_type", "malware_family", "reporter",
        "first_seen", "tags", "sources", "refs",
        "priority_override", "expires_at", "notes",
    ],
    "domain": [
        "value", "status", "threat_type", "malware_family", "reporter",
        "first_seen", "tags", "sources", "refs",
        "priority_override", "expires_at", "notes",
    ],
}

_LIST_FIELDS = {"tags", "sources", "refs"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX_MD5 = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")


def _check_type(t: str) -> None:
    if t not in _VALID:
        raise HTTPException(400, f"Invalid IOC type — must be one of: {', '.join(sorted(_VALID))}")


def _parse_list(val: str) -> list[str]:
    if not val:
        return []
    sep = "|" if "|" in val else ","
    return [s.strip() for s in val.split(sep) if s.strip()]


# ── Static routes first ────────────────────────────────────────────────────────

@router.get("/counts")
def ioc_counts(_u=Depends(get_current_user)):
    return {t: len(ioc_store.list(t)) for t in IOC_TYPES}


@router.post("/maintenance/run")
def run_maintenance(_u=Depends(require_manager)):
    results = ioc_store.run_maintenance()
    log_user_action(logger, "IOC maintenance completed: %s", results)
    return {"ok": True, "results": results}


# ── Sub-path routes (must precede bare /{ioc_type} and /{ioc_type}/{ioc_id}) ──

@router.get("/{ioc_type}/csv-template")
def csv_template(ioc_type: str, _u=Depends(get_current_user)):
    _check_type(ioc_type)
    cols = _CSV_COLS[ioc_type]
    content = ",".join(cols) + "\n"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ioc_{ioc_type}_template.csv"'},
    )


@router.post("/{ioc_type}/bulk-upload")
async def bulk_upload_iocs(
    ioc_type: str,
    file: UploadFile = File(...),
    priority_override: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    conflict_resolution: str = Form("csv_wins"),
    _u=Depends(require_manager),
):
    _check_type(ioc_type)
    expected_cols = set(_CSV_COLS[ioc_type])

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded")

    if not text.strip():
        raise HTTPException(400, "CSV file is empty")

    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise HTTPException(400, "CSV has no header row")

    fieldnames = [f.strip() for f in reader.fieldnames]
    if "value" not in fieldnames:
        raise HTTPException(
            400,
            f"CSV is missing the required 'value' column. Found: {', '.join(fieldnames[:10])}",
        )

    unknown = [f for f in fieldnames if f not in expected_cols]
    warnings: list[str] = []
    if unknown:
        warnings.append(f"Unknown columns ignored: {', '.join(unknown)}")

    form_priority = (priority_override or "").strip().lower() or None
    form_expires = (expires_at or "").strip() or None
    if form_priority and form_priority not in ("low", "medium", "high"):
        raise HTTPException(400, "priority_override must be low, medium, or high")
    if form_expires and not _DATE_RE.match(form_expires):
        raise HTTPException(400, "expires_at must be in YYYY-MM-DD format")

    records: list[dict] = []
    skipped: list[str] = []     # rows not imported (empty value)
    row_warnings: list[str] = []  # rows imported but with invalid fields cleared

    for row_num, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}

        value = row.get("value", "").strip()
        if not value:
            skipped.append(f"Row {row_num}: 'value' is empty — not imported")
            continue

        row_errors: list[str] = []

        status = row.get("status", "")
        if status and status not in ("online", "offline"):
            row_errors.append(f"status '{status}' invalid (use: online, offline)")
            row["status"] = ""

        csv_priority = row.get("priority_override", "").strip().lower()
        if csv_priority and csv_priority not in ("low", "medium", "high"):
            row_errors.append(f"priority_override '{csv_priority}' invalid (use: low, medium, high)")
            csv_priority = ""

        csv_expires = row.get("expires_at", "").strip()
        if csv_expires and not _DATE_RE.match(csv_expires):
            row_errors.append(f"expires_at '{csv_expires}' invalid (use YYYY-MM-DD)")
            csv_expires = ""

        first_seen = row.get("first_seen", "").strip()
        if first_seen and not _DATE_RE.match(first_seen):
            row_errors.append(f"first_seen '{first_seen}' invalid (use YYYY-MM-DD)")
            row["first_seen"] = ""

        if ioc_type == "ip":
            port_raw = row.get("port", "")
            if port_raw:
                try:
                    p = int(port_raw)
                    if not (1 <= p <= 65535):
                        row_errors.append(f"port {p} out of range 1–65535")
                        row["port"] = ""
                    else:
                        row["port"] = p
                except ValueError:
                    row_errors.append(f"port '{port_raw}' is not an integer")
                    row["port"] = ""

            country = row.get("country", "").strip()
            if country:
                if not re.match(r"^[A-Za-z]{2}$", country):
                    row_errors.append(f"country '{country}' must be a 2-letter code")
                    row["country"] = ""
                else:
                    row["country"] = country.upper()

            asn_raw = row.get("asn", "")
            if asn_raw:
                try:
                    row["asn"] = int(asn_raw)
                except ValueError:
                    row_errors.append(f"asn '{asn_raw}' is not an integer")
                    row["asn"] = ""

        if ioc_type == "hash":
            md5 = row.get("hash_md5", "").strip()
            if md5 and not _HEX_MD5.match(md5):
                row_errors.append("hash_md5 must be a 32-character hex string")
                row["hash_md5"] = ""

            sha1 = row.get("hash_sha1", "").strip()
            if sha1 and not _HEX_SHA1.match(sha1):
                row_errors.append("hash_sha1 must be a 40-character hex string")
                row["hash_sha1"] = ""

        if row_errors:
            row_warnings.append(f"Row {row_num} ({value[:40]}): {'; '.join(row_errors)} — imported with those fields cleared")

        # Resolve priority and expires_at based on conflict_resolution setting
        if conflict_resolution == "form_wins":
            effective_priority = form_priority or csv_priority
            effective_expires = form_expires or csv_expires
        else:  # csv_wins
            effective_priority = csv_priority or form_priority
            effective_expires = csv_expires or form_expires

        rec: dict = {"value": value}
        for col in _CSV_COLS[ioc_type]:
            if col in ("value", "priority_override", "expires_at"):
                continue
            v = row.get(col, "")
            if col in _LIST_FIELDS:
                rec[col] = _parse_list(v)
            elif col in ("port", "asn"):
                # Already converted to int above or left as empty string
                stored = row.get(col)
                rec[col] = stored if isinstance(stored, int) else None
            else:
                rec[col] = v if v else None

        if effective_priority:
            rec["priority_override"] = effective_priority
        if effective_expires:
            rec["expires_at"] = effective_expires

        records.append(rec)

    if not records:
        detail = "No valid rows found."
        if skipped:
            detail += f" First issue: {skipped[0]}"
        raise HTTPException(400, detail)

    added = ioc_store.create_batch(ioc_type, records)
    log_user_action(
        logger, "IOC bulk upload: [%s] %d processed, %d added, %d merged, %d skipped, %d with field corrections",
        ioc_type, len(records), added, len(records) - added, len(skipped), len(row_warnings),
    )
    return {
        "ok": True,
        "processed": len(records),
        "added": added,
        "merged": len(records) - added,
        "skipped": skipped,
        "row_warnings": row_warnings,
        "warnings": warnings,
    }


# ── Parameterized routes ───────────────────────────────────────────────────────

@router.get("/{ioc_type}")
def list_iocs(ioc_type: str, _u=Depends(get_current_user)):
    _check_type(ioc_type)
    return ioc_store.list(ioc_type)


@router.post("/{ioc_type}")
def create_ioc(ioc_type: str, data: dict, _u=Depends(require_manager)):
    _check_type(ioc_type)
    if not data.get("value", "").strip():
        raise HTTPException(400, "IOC value is required")
    record = ioc_store.create(ioc_type, data)
    log_user_action(logger, "IOC created/merged: [%s] %s", ioc_type, data.get("value"))
    return record


@router.put("/{ioc_type}/{ioc_id}")
def update_ioc(ioc_type: str, ioc_id: str, data: dict, _u=Depends(require_manager)):
    _check_type(ioc_type)
    record = ioc_store.update(ioc_type, ioc_id, data)
    if not record:
        raise HTTPException(404, "IOC not found")
    log_user_action(logger, "IOC updated: [%s] %s", ioc_type, record.get("value"))
    return record


@router.delete("/{ioc_type}/{ioc_id}")
def delete_ioc(ioc_type: str, ioc_id: str, _u=Depends(require_manager)):
    _check_type(ioc_type)
    if not ioc_store.delete(ioc_type, ioc_id):
        raise HTTPException(404, "IOC not found")
    log_user_action(logger, "IOC deleted: [%s] %s", ioc_type, ioc_id)
    return {"ok": True}
