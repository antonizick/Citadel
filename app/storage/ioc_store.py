"""IOC storage — SQLite-backed store for IPs, hashes, URLs, and domains.

DB file: data/iocs.db (single table, one row per IOC; type-specific fields
live in a JSON blob column since the record shape already varies per type).
Deduplication is by (ioc_type, normalised value). Sources/refs are merged on collision.
No record-count cap — only expiry-based pruning in run_maintenance().
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

IOC_TYPES = ("ip", "hash", "url", "domain")

_DB_PATH = Path("data/iocs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS iocs (
    id TEXT PRIMARY KEY,
    ioc_type TEXT NOT NULL,
    value TEXT NOT NULL,
    value_normalized TEXT NOT NULL,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    data TEXT NOT NULL,
    UNIQUE(ioc_type, value_normalized)
);
CREATE INDEX IF NOT EXISTS idx_iocs_type ON iocs(ioc_type);
"""

_EXTRA_EXCLUDE = ("id", "ioc_type", "value", "added_at", "updated_at", "expires_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_record(row: sqlite3.Row) -> dict:
    record = json.loads(row["data"])
    record.update({
        "id": row["id"],
        "ioc_type": row["ioc_type"],
        "value": row["value"],
        "added_at": row["added_at"],
        "updated_at": row["updated_at"],
    })
    if row["expires_at"]:
        record["expires_at"] = row["expires_at"]
    return record


def _record_to_row(ioc_type: str, record: dict) -> tuple:
    norm = record["value"].strip().lower()
    extra = {k: v for k, v in record.items() if k not in _EXTRA_EXCLUDE}
    return (
        record["id"], ioc_type, record["value"], norm,
        record["added_at"], record["updated_at"], record.get("expires_at"),
        json.dumps(extra),
    )


def _merge_lists(conn: sqlite3.Connection, existing_id: str, existing_data: str, data: dict, now: str) -> None:
    rec = json.loads(existing_data)
    changed = False
    for s in data.get("sources", []):
        if s not in rec.setdefault("sources", []):
            rec["sources"].append(s)
            changed = True
    for r in data.get("refs", []):
        if r not in rec.setdefault("refs", []):
            rec["refs"].append(r)
            changed = True
    if changed:
        conn.execute(
            "UPDATE iocs SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(rec), now, existing_id),
        )


class IocStore:
    def list(self, ioc_type: str) -> list[dict]:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM iocs WHERE ioc_type = ? ORDER BY added_at", (ioc_type,)
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get(self, ioc_type: str, ioc_id: str) -> Optional[dict]:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM iocs WHERE ioc_type = ? AND id = ?", (ioc_type, ioc_id)
            ).fetchone()
        return _row_to_record(row) if row else None

    def create_batch(self, ioc_type: str, records: list[dict]) -> int:
        """Bulk insert/merge. One connection for the whole batch. Returns count of new records added."""
        if not records:
            return 0
        now = _now()
        added = 0
        with _conn() as conn:
            for data in records:
                norm = data.get("value", "").strip().lower()
                if not norm:
                    continue
                existing = conn.execute(
                    "SELECT id, data FROM iocs WHERE ioc_type = ? AND value_normalized = ?",
                    (ioc_type, norm),
                ).fetchone()
                if existing:
                    _merge_lists(conn, existing["id"], existing["data"], data, now)
                else:
                    record = {**data, "id": str(uuid.uuid4()), "added_at": now, "updated_at": now}
                    conn.execute(
                        "INSERT INTO iocs (id, ioc_type, value, value_normalized, added_at, updated_at, expires_at, data) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        _record_to_row(ioc_type, record),
                    )
                    added += 1
        return added

    def create(self, ioc_type: str, data: dict) -> dict:
        """Insert new IOC or merge sources/refs into an existing duplicate."""
        norm = data.get("value", "").strip().lower()
        now = _now()
        with _conn() as conn:
            existing = conn.execute(
                "SELECT id, data FROM iocs WHERE ioc_type = ? AND value_normalized = ?",
                (ioc_type, norm),
            ).fetchone()
            if existing:
                _merge_lists(conn, existing["id"], existing["data"], data, now)
                row = conn.execute("SELECT * FROM iocs WHERE id = ?", (existing["id"],)).fetchone()
            else:
                record = {**data, "id": str(uuid.uuid4()), "added_at": now, "updated_at": now}
                conn.execute(
                    "INSERT INTO iocs (id, ioc_type, value, value_normalized, added_at, updated_at, expires_at, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    _record_to_row(ioc_type, record),
                )
                row = conn.execute("SELECT * FROM iocs WHERE id = ?", (record["id"],)).fetchone()
        return _row_to_record(row)

    def update(self, ioc_type: str, ioc_id: str, data: dict) -> Optional[dict]:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM iocs WHERE ioc_type = ? AND id = ?", (ioc_type, ioc_id)
            ).fetchone()
            if not row:
                return None
            rec = _row_to_record(row)
            for k, v in data.items():
                if k not in ("id", "added_at", "ioc_type"):
                    rec[k] = v
            rec["updated_at"] = _now()
            _, _, value, norm, added_at, updated_at, expires_at, blob = _record_to_row(ioc_type, rec)
            conn.execute(
                "UPDATE iocs SET value = ?, value_normalized = ?, updated_at = ?, expires_at = ?, data = ? "
                "WHERE id = ?",
                (value, norm, updated_at, expires_at, blob, ioc_id),
            )
        return rec

    def delete(self, ioc_type: str, ioc_id: str) -> bool:
        with _conn() as conn:
            cur = conn.execute("DELETE FROM iocs WHERE ioc_type = ? AND id = ?", (ioc_type, ioc_id))
        return cur.rowcount > 0

    def run_maintenance(self) -> dict:
        """Remove expired IOCs. No quantity cap."""
        now = datetime.now(timezone.utc)
        results: dict[str, dict] = {}

        def _is_expired(exp: Optional[str]) -> bool:
            if not exp:
                return False
            try:
                dt = datetime.fromisoformat(str(exp))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt < now
            except Exception:
                return False

        with _conn() as conn:
            for ioc_type in IOC_TYPES:
                rows = conn.execute(
                    "SELECT id, expires_at FROM iocs WHERE ioc_type = ?", (ioc_type,)
                ).fetchall()
                before = len(rows)
                expired_ids = [r["id"] for r in rows if _is_expired(r["expires_at"])]
                if expired_ids:
                    conn.executemany("DELETE FROM iocs WHERE id = ?", [(i,) for i in expired_ids])
                results[ioc_type] = {
                    "expired": len(expired_ids),
                    "capped": 0,
                    "remaining": before - len(expired_ids),
                }

        return results


ioc_store = IocStore()
