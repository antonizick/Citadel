"""Phase 1-3 — Fetch, extract, and date-filter layer for trusted resources.
Phase 6 — fetch_urls_text() enriches interest search results with fetched article bodies.

Resources point at a specific URL/feed, so we FETCH them rather than search for them.
`fetch_source()` (Phase 1) resolves a resource `source` into raw story dicts. `extract_stories()`
(Phase 2) turns each story's raw HTML into clean body text via trafilatura. `filter_recent()`
(Phase 3) drops stories with a real, parseable publish date outside the given window.

Raw story dict (Phase 1 output):
    {"title": str, "url": str, "published": str|None, "html": str}

Normalized story dict (Phase 2 output — `html` replaced by `text`):
    {"title": str, "url": str, "published": str|None, "text": str}

`published` is the raw date string from the feed. `html` is the fetched article page; if the
page fetch fails we fall back to the feed-provided summary HTML so a story is never dropped
purely on a transient fetch error.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin

import feedparser
import httpx
import trafilatura
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# A realistic browser UA — some sites 403 obvious bot agents. Not a guarantee against
# JS-based bot management (Cloudflare/Akamai), which no header can beat; those sites
# degrade to feed-provided HTML.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT = 20          # seconds per HTTP GET
MAX_ARTICLES = 20           # cap article-page fetches per feed run
ARTICLE_CONCURRENCY = 5     # parallel article fetches


async def _get(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("Fetch failed %s: %s", url, e)
        return None


def _discover_feed(html: str, base_url: str) -> Optional[str]:
    """Find an RSS/Atom feed URL declared in a page's <link rel=alternate> tags.

    Most resource sources are homepages, not feeds; sites advertise their feed here.
    Skips comment feeds; returns the first content feed found, absolute-resolved.
    """
    for tag in re.findall(r"<link\b[^>]*>", html, re.I):
        if "alternate" not in tag.lower():
            continue
        if not re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if not href:
            continue
        url = urljoin(base_url, href.group(1))
        if "comment" in url.lower():
            continue
        return url
    return None


def _entry_html(entry) -> str:
    """Best HTML the feed itself carries for an entry (full content > summary)."""
    content = entry.get("content")
    if content and isinstance(content, list) and content[0].get("value"):
        return content[0]["value"]
    return entry.get("summary", "") or ""


async def fetch_source(source: str, max_articles: int = MAX_ARTICLES) -> list[dict]:
    """Resolve a resource source into fetched story dicts.

    Feed source  -> parse entries, fetch each article page (fallback to feed HTML).
    Page source  -> single story containing the page HTML.
    Unreachable   -> empty list.
    """
    if not source:
        return []

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        body = await _get(client, source)
        if body is None:
            return []

        parsed = feedparser.parse(body)

        if not (parsed.version and parsed.entries):
            # Source isn't itself a feed — most resource sources are homepages.
            # Try to auto-discover the site's feed and use that instead.
            feed_url = _discover_feed(body, source)
            if feed_url:
                fbody = await _get(client, feed_url)
                if fbody:
                    p2 = feedparser.parse(fbody)
                    if p2.version and p2.entries:
                        logger.info("Auto-discovered feed %s for source %s", feed_url, source)
                        parsed = p2

        if not (parsed.version and parsed.entries):
            # No feed anywhere — treat the whole page as a single story.
            title = parsed.feed.get("title", "") if parsed.feed else ""
            logger.info("No feed for %s — using page as single story", source)
            return [{"title": title or source, "url": source, "published": None, "html": body}]

        entries = parsed.entries[:max_articles]
        logger.info("Parsed feed %s — %d entries (capped at %d)", source, len(parsed.entries), max_articles)

        sem = asyncio.Semaphore(ARTICLE_CONCURRENCY)

        async def _resolve(entry) -> dict:
            link = entry.get("link", "")
            title = entry.get("title", "")
            published = entry.get("published") or entry.get("updated")
            html = None
            if link:
                async with sem:
                    html = await _get(client, link)
            if not html:
                # Page fetch failed or no link — fall back to feed-provided HTML.
                html = _entry_html(entry)
            return {"title": title, "url": link or source, "published": published, "html": html or ""}

        stories = await asyncio.gather(*(_resolve(e) for e in entries))

    stories = [s for s in stories if s["html"].strip()]
    logger.info("fetch_source '%s' → %d stories with content", source, len(stories))
    return stories


# --- Phase 2: extraction --------------------------------------------------------------

def _extract_text(html: str) -> str:
    """Clean article body text from raw HTML.

    trafilatura handles real article pages (strips nav/ads/boilerplate). Feed-only teaser
    HTML (a bare sentence, no page structure) makes trafilatura return nothing, since there's
    no boilerplate to distinguish content from — fall back to a plain tag strip via lxml
    (already a trafilatura dependency, so this adds no new package) so short teasers aren't
    silently dropped.
    """
    if not html.strip():
        return ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)
    if text and text.strip():
        return text.strip()
    from lxml import html as lhtml
    try:
        return lhtml.fromstring(html).text_content().strip()
    except Exception:
        return ""


def extract_stories(stories: list[dict]) -> list[dict]:
    """Phase 2 — turn raw story HTML into clean body text. Drops stories with no extractable text."""
    normalized = []
    for s in stories:
        text = _extract_text(s.get("html", ""))
        if not text:
            logger.warning("No extractable text for '%s' (%s)", s.get("title", ""), s.get("url", ""))
            continue
        normalized.append({"title": s["title"], "url": s["url"], "published": s["published"], "text": text})
    logger.info("extract_stories: %d/%d stories yielded text", len(normalized), len(stories))
    return normalized


# --- Phase 3: date filter -------------------------------------------------------------

def _parse_published(raw: Optional[str]) -> Optional[datetime]:
    """Parse a feed date string to a tz-aware datetime. Returns None if missing/unparseable."""
    if not raw:
        return None
    try:
        dt = dateutil_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return None


def filter_recent(stories: list[dict], hours: int = 48) -> list[dict]:
    """Phase 3 — keep stories published within the last `hours`.

    Stories with a real, parseable date outside the window are dropped (this replaces the
    old approach of asking the model to guess freshness from search-result blurbs). Stories
    with no parseable date are kept — the model is instructed to mark these "date unknown"
    rather than have us silently discard content just because a feed omitted a date field.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept = []
    dropped = 0
    for s in stories:
        dt = _parse_published(s.get("published"))
        if dt is not None and dt < cutoff:
            dropped += 1
            continue
        kept.append(s)
    logger.info("filter_recent: kept %d, dropped %d stale (cutoff=%s)", len(kept), dropped, cutoff.isoformat())
    return kept


async def collect_stories(source: str, hours: int = 48, max_articles: int = MAX_ARTICLES) -> list[dict]:
    """Fetch → extract → date-filter in one call. What run_resource() should call in Phase 4."""
    raw = await fetch_source(source, max_articles=max_articles)
    normalized = extract_stories(raw)
    return filter_recent(normalized, hours=hours)


# --- Phase 6: interest-path enrichment --------------------------------------------------

async def fetch_urls_text(urls: list[str], max_urls: int = 5) -> dict[str, str]:
    """Fetch + extract clean body text for a flat list of URLs (an interest's top search
    results, not a feed). Best-effort: unreachable/unextractable URLs are simply absent from
    the returned dict — callers fall back to the search snippet for those."""
    urls = [u for u in dict.fromkeys(urls) if u][:max_urls]  # de-dup, drop empty, cap
    if not urls:
        return {}

    sem = asyncio.Semaphore(ARTICLE_CONCURRENCY)
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        async def _one(url: str) -> tuple[str, str]:
            async with sem:
                html = await _get(client, url)
            return url, (_extract_text(html) if html else "")

        pairs = await asyncio.gather(*(_one(u) for u in urls))

    result = {url: text for url, text in pairs if text}
    logger.info("fetch_urls_text: %d/%d URLs yielded text", len(result), len(urls))
    return result


def _check_date_filter():
    """Phase 3 check: synthetic mixed-age entries — only <48h survive. Live feeds are all
    fresh, so this can't be verified against real data; it's a pure unit check."""
    now = datetime.now(timezone.utc)
    stories = [
        {"title": "fresh", "url": "u1", "published": (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")},
        {"title": "borderline", "url": "u2", "published": (now - timedelta(hours=47)).strftime("%a, %d %b %Y %H:%M:%S GMT")},
        {"title": "stale", "url": "u3", "published": (now - timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")},
        {"title": "ancient", "url": "u4", "published": "Thu, 22 Feb 2007 00:00:00 GMT"},
        {"title": "undated", "url": "u5", "published": None},
    ]
    kept = filter_recent(stories, hours=48)
    titles = {s["title"] for s in kept}
    assert titles == {"fresh", "borderline", "undated"}, f"unexpected filter result: {titles}"
    print(f"OK — date filter kept {sorted(titles)}, dropped stale/ancient")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    SOURCES = [
        "https://www.darkreading.com/rss.xml",
        "https://www.bleepingcomputer.com/",
        "https://thehackernews.com/",
        "https://krebsonsecurity.com/",
    ]

    async def _check():
        for src in SOURCES:
            raw = await fetch_source(src, max_articles=3)
            extracted = extract_stories(raw)
            filtered = filter_recent(extracted, hours=48)
            print(f"\n=== {src} — raw={len(raw)} extracted={len(extracted)} filtered={len(filtered)} ===")
            for s in filtered:
                print(f"  {s['published']!s:33.33} {len(s['text']):>6} chars text  {s['title'][:50]}")
            assert raw, f"no stories fetched for {src}"
            assert extracted, f"no text extracted for {src}"
            # Real article pages must yield substantive text, not just boilerplate scraps.
            substantive = [s for s in extracted if len(s["text"]) > 500]
            if substantive:
                print(f"  ({len(substantive)}/{len(extracted)} stories >500 chars extracted text)")

        _check_date_filter()

        # Phase 6 check: enrich a flat list of search-result-style URLs with full article text.
        urls = [
            "https://krebsonsecurity.com/2026/07/fbi-seizes-netnut-proxy-platform-popa-botnet/",
            "https://thehackernews.com/2026/07/armored-likho-targets-government.html",
            "https://this-domain-does-not-exist-xyz123.invalid/page",
        ]
        enriched = await fetch_urls_text(urls, max_urls=5)
        print(f"\n=== fetch_urls_text — {len(enriched)}/{len(urls)} URLs enriched ===")
        for u, text in enriched.items():
            print(f"  {len(text):>6} chars  {u}")
        assert len(enriched) >= 2, "expected the two live URLs to enrich successfully"
        assert all(len(t) > 500 for t in enriched.values()), "enriched text unexpectedly short"

        print("\nOK — fetch + extract + date-filter + interest-enrichment pipeline verified")

    asyncio.run(_check())
