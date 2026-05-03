import logging
from datetime import datetime, timezone
from typing import Optional
from app.config import get_config

logger = logging.getLogger(__name__)

# Map schedule frequency → DDG timelimit so searches stay fresh relative to run cadence
def _timelimit_for_schedule(schedule: dict) -> str:
    stype = schedule.get("type", "interval")
    if stype == "manual":
        return "m"
    if stype == "weekly":
        return "m"
    unit = schedule.get("interval_unit", "days")
    value = int(schedule.get("interval_value", 1))
    hours = {"minutes": 1/60, "hours": 1, "days": 24, "weeks": 168}.get(unit, 24) * value
    if hours <= 24:
        return "d"   # past day
    if hours <= 72:
        return "w"   # past week
    return "m"       # past month


def _build_queries(name: str, keywords: list[str]) -> list[str]:
    """Return a prioritized list of search queries instead of one keyword blob."""
    year = datetime.now(timezone.utc).year
    queries = [f"{name} {year}"]          # primary: name + current year forces recency
    for kw in keywords[:4]:               # up to 4 individual keyword searches
        if kw.lower() != name.lower():
            queries.append(f"{kw} {year}")
    return queries


async def search_web(
    query: str,
    max_results: Optional[int] = None,
    timelimit: Optional[str] = None,
) -> list[dict]:
    config = get_config()
    n = max_results or config.search.max_results
    provider = config.search.provider

    if provider == "serpapi" and config.search.serpapi_key:
        return await _serpapi_search(query, n, config.search.serpapi_key, timelimit)
    if provider == "brave" and config.search.brave_api_key:
        return await _brave_search(query, n, config.search.brave_api_key, timelimit)
    return await _ddg_search(query, n, timelimit)


async def search_multi(
    name: str,
    keywords: list[str],
    schedule: dict,
    max_results: Optional[int] = None,
) -> list[dict]:
    """Run multiple targeted queries and deduplicate by URL."""
    config = get_config()
    per_query = max(5, (max_results or config.search.max_results) // 2)
    timelimit = _timelimit_for_schedule(schedule)
    queries = _build_queries(name, keywords)

    seen_urls: set[str] = set()
    combined: list[dict] = []

    for q in queries:
        results = await search_web(q, max_results=per_query, timelimit=timelimit)
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(r)

    logger.info(
        "Multi-search '%s' — %d queries, timelimit=%s, %d unique results",
        name, len(queries), timelimit, len(combined),
    )
    return combined


async def _ddg_search(query: str, max_results: int, timelimit: Optional[str] = None) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        kwargs = {"max_results": max_results}
        if timelimit:
            kwargs["timelimit"] = timelimit
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, **kwargs):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "source": "duckduckgo",
                })
        logger.info("DDG '%s' (timelimit=%s) → %d results", query, timelimit, len(results))
        return results
    except Exception as e:
        logger.error("DDG search failed for '%s': %s", query, e)
        return []


async def _brave_search(query: str, max_results: int, api_key: str, timelimit: Optional[str] = None) -> list[dict]:
    import httpx
    # Brave uses freshness param: pd=day, pw=week, pm=month
    freshness_map = {"d": "pd", "w": "pw", "m": "pm"}
    try:
        params = {"q": query, "count": min(max_results, 20)}
        if timelimit and timelimit in freshness_map:
            params["freshness"] = freshness_map[timelimit]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
                "source": "brave",
            })
        logger.info("Brave '%s' (timelimit=%s) → %d results", query, timelimit, len(results))
        return results
    except Exception as e:
        logger.error("Brave search failed for '%s': %s", query, e)
        return []


async def _serpapi_search(query: str, max_results: int, api_key: str, timelimit: Optional[str] = None) -> list[dict]:
    import httpx
    # SerpAPI uses tbs param for date filtering
    tbs_map = {"d": "qdr:d", "w": "qdr:w", "m": "qdr:m"}
    try:
        params = {"q": query, "api_key": api_key, "num": max_results, "engine": "google"}
        if timelimit and timelimit in tbs_map:
            params["tbs"] = tbs_map[timelimit]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("organic_results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "source": "serpapi",
            })
        logger.info("SerpAPI '%s' (timelimit=%s) → %d results", query, timelimit, len(results))
        return results
    except Exception as e:
        logger.error("SerpAPI search failed for '%s': %s", query, e)
        return []


async def search_trusted_resource(url: str, query: str) -> list[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Nx-Citadel/1.0"})
        return [{
            "title": f"Trusted: {url}",
            "url": url,
            "snippet": resp.text[:500].strip(),
            "source": "trusted_resource",
        }]
    except Exception as e:
        logger.warning("Failed to fetch trusted resource %s: %s", url, e)
        return []
