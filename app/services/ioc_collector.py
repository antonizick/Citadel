"""IOC feed collection — one async function per source, plus run_all_collections()."""
import asyncio
import csv
import io
import logging
from typing import Optional

import httpx

from app.ioc_config import get_ioc_config
from app.ioc_sync_status import record_run_start, record_source_result
from app.storage.ioc_store import ioc_store

logger = logging.getLogger(__name__)

_TIMEOUT = 30


# ── Feodo Tracker ─────────────────────────────────────────────────────────────

async def collect_feodo_tracker() -> int:
    url = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        entries = resp.json()

    records = []
    for entry in entries:
        ip = (entry.get("ip_address") or "").strip()
        if not ip:
            continue
        records.append({
            "value": ip,
            "port": entry.get("port"),
            "status": "online" if entry.get("status") == "online" else "offline",
            "threat_type": "c2",
            "malware_family": entry.get("malware"),
            "country": entry.get("country"),
            "asn": entry.get("as_number"),
            "asn_name": entry.get("as_name"),
            "hostname": entry.get("hostname"),
            "first_seen": entry.get("first_seen"),
            "sources": ["feodo_tracker"],
            "refs": ["https://feodotracker.abuse.ch/"],
        })

    count = await asyncio.to_thread(ioc_store.create_batch, "ip", records)
    logger.info("Feodo Tracker: %d IPs ingested", count)
    return count


# ── URLhaus ───────────────────────────────────────────────────────────────────

async def collect_urlhaus() -> int:
    feed_url = "https://urlhaus.abuse.ch/downloads/csv_recent/"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()

    records = []
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if not row or row[0].startswith("#"):
            continue
        # id, dateadded, url, url_status, last_online, threat, tags, urlhaus_link, reporter
        if len(row) < 9:
            continue
        url_val = row[2].strip()
        if not url_val:
            continue
        tags_raw = row[6].strip()
        tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []
        ref = row[7].strip()
        records.append({
            "value": url_val,
            "status": "online" if row[3].strip() == "online" else "offline",
            "threat_type": row[5].strip() or None,
            "tags": tags,
            "reporter": row[8].strip() or None,
            "first_seen": row[1].strip() or None,
            "sources": ["urlhaus"],
            "refs": [ref] if ref else [],
        })

    count = await asyncio.to_thread(ioc_store.create_batch, "url", records)
    logger.info("URLhaus: %d URLs ingested", count)
    return count


# ── MalwareBazaar ─────────────────────────────────────────────────────────────

async def collect_malwarebazaar() -> int:
    feed_url = "https://bazaar.abuse.ch/export/csv/recent/"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()

    records = []
    reader = csv.reader(io.StringIO(resp.text), skipinitialspace=True)
    for row in reader:
        if not row or row[0].startswith("#"):
            continue
        # first_seen_utc, sha256, md5, sha1, reporter, file_name, file_type_guess,
        # mime_type, signature, clamav, vtpercent, imphash, ssdeep, tlsh
        if len(row) < 9:
            continue
        sha256 = row[1].strip().strip('"')
        if not sha256 or len(sha256) != 64:
            continue
        def _c(val: str) -> str | None:
            v = val.strip().strip('"').strip()
            return v if v and v.lower() not in ("n/a", "none") else None
        signature = row[8].strip().strip('"').strip()
        records.append({
            "value": sha256,
            "hash_md5": _c(row[2]),
            "hash_sha1": _c(row[3]),
            "file_type": _c(row[6]),
            "malware_family": signature if signature not in ("", "n/a") else None,
            "reporter": _c(row[4]),
            "file_name": _c(row[5]),
            "first_seen": row[0].strip() or None,
            "sources": ["malwarebazaar"],
            "refs": [f"https://bazaar.abuse.ch/sample/{sha256}/"],
        })

    count = await asyncio.to_thread(ioc_store.create_batch, "hash", records)
    logger.info("MalwareBazaar: %d hashes ingested", count)
    return count


# ── OpenPhish ─────────────────────────────────────────────────────────────────

async def collect_openphish() -> int:
    feed_url = "https://openphish.com/feed.txt"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()

    records = []
    for line in resp.text.splitlines():
        url_val = line.strip()
        if not url_val or not url_val.startswith("http"):
            continue
        records.append({
            "value": url_val,
            "status": "online",
            "threat_type": "phishing",
            "sources": ["openphish"],
            "refs": ["https://openphish.com/"],
        })

    count = await asyncio.to_thread(ioc_store.create_batch, "url", records)
    logger.info("OpenPhish: %d URLs ingested", count)
    return count


# ── ThreatFox ─────────────────────────────────────────────────────────────────

async def collect_threatfox(api_key: str) -> int:
    endpoint = "https://threatfox-api.abuse.ch/api/v1/"
    payload = {"query": "get_iocs", "days": 1}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(endpoint, json=payload, headers={"Auth-Key": api_key})
        resp.raise_for_status()
        data = resp.json()

    if data.get("query_status") != "ok":
        raise ValueError(f"ThreatFox error: {data.get('query_status')}")

    batches: dict[str, list] = {"ip": [], "domain": [], "url": [], "hash": []}

    for entry in data.get("data") or []:
        ioc_val = (entry.get("ioc") or "").strip()
        ioc_type_raw = (entry.get("ioc_type") or "").lower()
        if not ioc_val:
            continue

        tags = entry.get("tags") or []
        base = {
            "threat_type": entry.get("threat_type"),
            "malware_family": entry.get("malware") or entry.get("malware_alias"),
            "confidence": entry.get("confidence_level"),
            "first_seen": entry.get("first_seen"),
            "sources": ["threatfox"],
            "refs": [entry.get("reference")] if entry.get("reference") else [],
            "tags": tags,
            "reporter": "abuse.ch/threatfox",
        }

        if ioc_type_raw == "ip:port":
            parts = ioc_val.rsplit(":", 1)
            ip = parts[0].strip("[]")
            port = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None
            batches["ip"].append({**base, "value": ip, "port": port, "threat_type": base.get("threat_type") or "c2"})
        elif ioc_type_raw == "domain":
            batches["domain"].append({**base, "value": ioc_val})
        elif ioc_type_raw == "url":
            batches["url"].append({**base, "value": ioc_val})
        elif ioc_type_raw in ("md5_hash", "sha256_hash"):
            batches["hash"].append({**base, "value": ioc_val})

    count = 0
    for ioc_type, records in batches.items():
        if records:
            count += await asyncio.to_thread(ioc_store.create_batch, ioc_type, records)

    logger.info("ThreatFox: %d IOCs ingested", count)
    return count


# ── OTX AlienVault ────────────────────────────────────────────────────────────

async def collect_otx(api_key: str) -> int:
    base_url = "https://otx.alienvault.com"
    headers = {"X-OTX-API-KEY": api_key}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/api/v1/pulses/subscribed",
            headers=headers,
            params={"limit": 20, "modified_since": ""},
        )
        resp.raise_for_status()
        data = resp.json()

    _OTX_TYPE_MAP = {
        "IPv4": "ip", "IPv6": "ip",
        "domain": "domain", "hostname": "domain",
        "URL": "url",
        "FileHash-MD5": "hash", "FileHash-SHA256": "hash", "FileHash-SHA1": "hash",
    }

    batches: dict[str, list] = {"ip": [], "domain": [], "url": [], "hash": []}

    for pulse in data.get("results") or []:
        tags = pulse.get("tags") or []
        mf = pulse.get("malware_families") or []
        if mf:
            family = mf[0].get("display_name", "") if isinstance(mf[0], dict) else str(mf[0])
        else:
            family = ""
        sources = ["otx"]
        refs = [f"{base_url}/pulse/{pulse.get('id', '')}"]

        for ind in pulse.get("indicators") or []:
            ind_type = ind.get("type", "")
            citadel_type = _OTX_TYPE_MAP.get(ind_type)
            if not citadel_type:
                continue
            val = (ind.get("indicator") or "").strip()
            if not val:
                continue

            record = {
                "value": val,
                "malware_family": family or None,
                "first_seen": ind.get("created"),
                "sources": sources,
                "refs": refs,
                "tags": tags,
                "reporter": pulse.get("author_name"),
            }
            if citadel_type == "hash":
                if ind_type == "FileHash-MD5":
                    record["hash_md5"] = val
                elif ind_type == "FileHash-SHA1":
                    record["hash_sha1"] = val
            batches[citadel_type].append(record)

    count = 0
    for ioc_type, records in batches.items():
        if records:
            count += await asyncio.to_thread(ioc_store.create_batch, ioc_type, records)

    logger.info("OTX: %d IOCs ingested", count)
    return count


# ── Orchestrator ──────────────────────────────────────────────────────────────

_COLLECTORS = {
    "feodo_tracker": (collect_feodo_tracker, False),
    "urlhaus":        (collect_urlhaus,        False),
    "malwarebazaar":  (collect_malwarebazaar,   False),
    "openphish":      (collect_openphish,       False),
    "threatfox":      (collect_threatfox,       True),
    "otx":            (collect_otx,             True),
}

_SOURCE_LABELS = {
    "feodo_tracker": "Feodo Tracker",
    "urlhaus":       "URLhaus",
    "malwarebazaar": "MalwareBazaar",
    "openphish":     "OpenPhish",
    "threatfox":     "ThreatFox",
    "otx":           "AlienVault OTX",
}


async def run_all_collections(next_run_iso: Optional[str] = None) -> dict:
    """Pull all enabled IOC sources. Returns per-source results."""
    record_run_start(next_run_iso)
    cfg = get_ioc_config()
    results = {}

    for source, (fn, needs_key) in _COLLECTORS.items():
        src_cfg = getattr(cfg, source)
        if not src_cfg.enabled:
            results[source] = {"skipped": True}
            continue

        if needs_key and not src_cfg.api_key:
            msg = "API key not configured"
            logger.warning("%s: %s", _SOURCE_LABELS[source], msg)
            record_source_result(source, 0, msg)
            results[source] = {"count": 0, "error": msg}
            continue

        try:
            if needs_key:
                count = await fn(src_cfg.api_key)
            else:
                count = await fn()
            record_source_result(source, count)
            results[source] = {"count": count, "error": None}
        except Exception as e:
            err = str(e)
            logger.error("%s collection failed: %s", _SOURCE_LABELS[source], err)
            record_source_result(source, 0, err)
            results[source] = {"count": 0, "error": err}

    return results
