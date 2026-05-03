"""IOC storage — one YAML-frontmatter markdown file per IOC type.

Files:
    data/iocs/ips.md
    data/iocs/hashes.md
    data/iocs/urls.md
    data/iocs/domains.md

Each file stores all records of that type as a YAML list in the frontmatter.
Deduplication is by normalised value. Sources/refs are merged on collision.
"""
from __future__ import annotations

import uuid
import frontmatter
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

IOC_TYPES = ("ip", "hash", "url", "domain")
MAX_RECORDS = 1000

_DATA_DIR = Path("data/iocs")
_FILES: dict[str, Path] = {
    "ip":     _DATA_DIR / "ips.md",
    "hash":   _DATA_DIR / "hashes.md",
    "url":    _DATA_DIR / "urls.md",
    "domain": _DATA_DIR / "domains.md",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure(ioc_type: str) -> None:
    path = _FILES[ioc_type]
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post("", ioc_type=ioc_type, last_updated=_now(), ioc_count=0, iocs=[])
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


def _load(ioc_type: str) -> list[dict]:
    _ensure(ioc_type)
    post = frontmatter.load(str(_FILES[ioc_type]))
    return list(post.metadata.get("iocs") or [])


def _save(ioc_type: str, iocs: list[dict]) -> None:
    path = _FILES[ioc_type]
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        "",
        ioc_type=ioc_type,
        last_updated=_now(),
        ioc_count=len(iocs),
        iocs=iocs,
    )
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


class IocStore:
    def list(self, ioc_type: str) -> list[dict]:
        return _load(ioc_type)

    def get(self, ioc_type: str, ioc_id: str) -> Optional[dict]:
        return next((r for r in _load(ioc_type) if r.get("id") == ioc_id), None)

    def create_batch(self, ioc_type: str, records: list[dict]) -> int:
        """Bulk insert/merge. One file read + one write. Returns count of new records added."""
        if not records:
            return 0
        iocs = _load(ioc_type)
        index: dict[str, int] = {
            rec.get("value", "").strip().lower(): i for i, rec in enumerate(iocs)
        }
        now = _now()
        added = 0
        dirty = False

        for data in records:
            norm = data.get("value", "").strip().lower()
            if not norm:
                continue
            if norm in index:
                rec = iocs[index[norm]]
                for s in data.get("sources", []):
                    if s not in rec.setdefault("sources", []):
                        rec["sources"].append(s)
                        dirty = True
                for r in data.get("refs", []):
                    if r not in rec.setdefault("refs", []):
                        rec["refs"].append(r)
                        dirty = True
                if dirty:
                    rec["updated_at"] = now
            else:
                if len(iocs) >= MAX_RECORDS:
                    continue
                record = {
                    **data,
                    "id": str(uuid.uuid4()),
                    "ioc_type": ioc_type,
                    "added_at": now,
                    "updated_at": now,
                }
                iocs.append(record)
                index[norm] = len(iocs) - 1
                added += 1
                dirty = True

        if dirty:
            _save(ioc_type, iocs)
        return added

    def create(self, ioc_type: str, data: dict) -> dict:
        """Insert new IOC or merge sources/refs into an existing duplicate."""
        iocs = _load(ioc_type)
        norm = data.get("value", "").strip().lower()

        for rec in iocs:
            if rec.get("value", "").strip().lower() == norm:
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
                    rec["updated_at"] = _now()
                    _save(ioc_type, iocs)
                return rec

        now = _now()
        record = {
            **data,
            "id": str(uuid.uuid4()),
            "ioc_type": ioc_type,
            "added_at": now,
            "updated_at": now,
        }
        iocs.append(record)
        _save(ioc_type, iocs)
        return record

    def update(self, ioc_type: str, ioc_id: str, data: dict) -> Optional[dict]:
        iocs = _load(ioc_type)
        for rec in iocs:
            if rec.get("id") == ioc_id:
                for k, v in data.items():
                    if k not in ("id", "added_at", "ioc_type"):
                        rec[k] = v
                rec["updated_at"] = _now()
                _save(ioc_type, iocs)
                return rec
        return None

    def delete(self, ioc_type: str, ioc_id: str) -> bool:
        iocs = _load(ioc_type)
        filtered = [r for r in iocs if r.get("id") != ioc_id]
        if len(filtered) == len(iocs):
            return False
        _save(ioc_type, filtered)
        return True

    def run_maintenance(self) -> dict:
        """Remove expired IOCs and enforce MAX_RECORDS cap (FIFO, expiry-protected records last)."""
        now = datetime.now(timezone.utc)
        results: dict[str, dict] = {}

        for ioc_type in IOC_TYPES:
            iocs = _load(ioc_type)
            before = len(iocs)

            def _is_expired(rec: dict) -> bool:
                exp = rec.get("expires_at")
                if not exp:
                    return False
                try:
                    dt = datetime.fromisoformat(str(exp))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt < now
                except Exception:
                    return False

            iocs = [r for r in iocs if not _is_expired(r)]
            expired = before - len(iocs)

            capped = 0
            if len(iocs) > MAX_RECORDS:
                protected = [r for r in iocs if r.get("expires_at")]
                unprotected = sorted(
                    [r for r in iocs if not r.get("expires_at")],
                    key=lambda r: r.get("added_at", ""),
                )
                excess = len(iocs) - MAX_RECORDS
                if excess <= len(unprotected):
                    unprotected = unprotected[excess:]
                    capped = excess
                else:
                    capped = len(unprotected)
                    unprotected = []
                    extra = excess - capped
                    protected = sorted(protected, key=lambda r: r.get("added_at", ""))[extra:]
                    capped += extra
                iocs = protected + unprotected

            _save(ioc_type, iocs)
            results[ioc_type] = {
                "expired": expired,
                "capped": capped,
                "remaining": len(iocs),
            }

        return results


ioc_store = IocStore()
