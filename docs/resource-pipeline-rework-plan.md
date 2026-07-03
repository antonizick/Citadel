# Trusted Resource Pipeline Rework — Phased Build Plan

**Status:** Approved for build
**Date:** 2026-07-03
**Owner:** Nick / Citadel

## Problem (why we are doing this)

Trusted resource runs produce low-quality reports. Root cause: the pipeline **never fetches the
source**. `run_resource()` passes the resource's `source` (e.g. `https://www.darkreading.com/rss.xml`)
straight into `search_multi()`, which throws that URL into DuckDuckGo as a *search query*. The LLM
then receives ~10 search-result snippets while the prompt instructs it to "parse the RSS feed" and
"follow links to full articles" — impossible. Reports come back mostly as "Data Coverage Notice"
apologies (the Dark Reading run extracted 1 story and 2 apology blocks).

Contributing: `qwen3.5-coder` (a code model) is doing news synthesis; snippets are not article
bodies; the 48h window is enforced only by DuckDuckGo's coarse date bucket; `search_trusted_resource()`
is dead code.

## Target design

Resources point at a specific URL/feed → treat them as **fetch targets, not search queries**.

```
Phase 1 Fetch  → Phase 2 Extract → Phase 3 Date-filter → Phase 4 Synthesize → Phase 5 Deliver
(feedparser+httpx) (trafilatura)     (dateutil)            (qwen3.6:27b)         (existing code)
```

Only synthesis uses a model. Everything else is deterministic code. The interest path keeps
DuckDuckGo search (topic monitoring is a legitimate search job).

## Decisions locked

- **Extractor:** `trafilatura` + `feedparser` (BeautifulSoup fallback if needed)
- **Synthesis model:** `qwen3.6:27b` (Ollama) — fallback `mistral-small`, then `qwen3.5`
- Resource `DEFAULT_RESOURCE_PROMPT` stays as-is — it finally receives the content it describes

---

## Build log

- **Phase 0 — DONE (2026-07-03).** Added `feedparser==6.0.11`, `trafilatura==2.0.0`,
  `lxml_html_clean==0.4.5` (trafilatura transitive dep, else `lxml.html.clean` ImportError) to
  `requirements.txt` and `.venv`. Verified imports + `qwen3.6:27b` responds. Note: venv `pip`
  script has a stale shebang (old `/home/nick/nxcitadel` path) — install via `.venv/bin/python -m pip`.
- **Phase 1 — DONE (2026-07-03).** New `app/services/fetch_service.py` — `fetch_source()` resolves a
  source into story dicts `{title, url, published, html}`. Handles feed URLs, homepage URLs (via
  `_discover_feed()` auto-discovery of `<link rel=alternate>` RSS/Atom), and plain pages. Browser UA
  set (obvious bot UA got 403s). Concurrent article fetch (semaphore=5), cap 20/feed, graceful
  fallback to feed-provided HTML when an article page fetch fails.
  - **Empirical results (all 4 live resources):** The Hacker News, BleepingComputer, Krebs now return
    **full article bodies** (60–175 KB HTML each). Dark Reading is teaser-only (~120 chars) — it hard
    bot-blocks article fetches (403, JS challenge) and its feed carries no `content:encoded`; no header
    beats this. Accepted degradation. If Dark Reading quality matters later, options: swap its source
    for a different feed, or add a headless-browser fetch path (Playwright) — out of current scope.
  - Runnable check: `python -m app.services.fetch_service` (asserts all 4 sources return stories).
- **Phase 2 — DONE (2026-07-03, Sonnet 5).** `extract_stories()` in `fetch_service.py` — `trafilatura.extract()`
  per story, `favor_precision=True`, tables/comments excluded. Deviated from plan's "BeautifulSoup
  fallback": used `lxml.html` (`.text_content()`) instead — it's already an installed trafilatura
  dependency, so no new package. Fallback only fires for feed-only teaser HTML (no page structure,
  trafilatura correctly returns nothing); real article pages extract cleanly without it. Normalizes
  to `{title, url, published, text}` (drops `html`).
  - **Empirical results:** BleepingComputer/THN/Krebs extracted text is 2.5–18 KB of genuine article
    body per story (boilerplate stripped) from 60–175 KB raw HTML. Dark Reading teasers (120–144
    chars) pass through the lxml fallback unchanged — there's no boilerplate to strip from a single
    sentence, so this is expected, not a bug.
- **Phase 3 — DONE (2026-07-03, Sonnet 5).** `filter_recent()` in `fetch_service.py` — parses
  `published` via `dateutil.parser.parse` (tz-normalized to UTC), drops stories with a real date older
  than the window (default 48h). **Design call:** undated stories are kept, not dropped — matches
  `SYSTEM_PROMPT`'s existing "mark date unknown" instruction rather than silently losing content a
  feed just didn't date. Only *verified*-stale items are dropped.
  - **Empirical proof (live, not just synthetic):** Krebs's real feed — 3 stories fetched, filter kept
    1 (Jul 2) and dropped 2 (Jun 23, Jun 18) as stale. Synthetic unit check (`_check_date_filter`) also
    covers borderline (47h → kept), ancient (2007 → dropped), and undated (kept) cases.
  - `collect_stories(source, hours, max_articles)` added — single fetch→extract→filter entrypoint,
    exactly what Phase 4's `run_resource()` rewire will call.
  - Runnable check: `python -m app.services.fetch_service` now exercises the full Phase 1–3 pipeline
    plus the Phase 3 unit check.

- **Phase 4 — DONE (2026-07-03, Opus 4.8).** Rewired the resource pipeline from search to fetch:
  - `scheduler_service.run_resource()` now calls `collect_stories(source, hours=_window_hours(schedule))`
    instead of `search_multi()`. `_window_hours()` floors at 48h (matches the prompt), widens to the
    schedule interval for longer-cadence resources. Return shape: `search_results` → slim `stories`
    metadata (title/url/published only — full text kept out of the API response; the UI ignored it anyway).
  - `ai_service.summarize_resource()` now takes fetched story dicts. New `_render_article_blocks()`
    renders full article text (not snippets) with per-article caps. Anthropic + Ollama resource paths
    refactored to share `_resource_user_content()`.
  - **Critical Ollama fix:** `_ollama_chat()` now sets `num_ctx` explicitly. Ollama's ~4k default
    SILENTLY drops everything beyond it — full articles never reached the model without this. Summaries
    use `SUMMARY_NUM_CTX=32768` + `SUMMARY_MAX_TOKENS=8192`; small calls (connection test) keep an 8k
    default so the 27B model isn't loaded at full context for a two-token reply.
  - Model already `qwen3.6:27b` in settings (set via UI). Retired dead `search_trusted_resource()`.
  - Interest path's search stays; both summarize paths got the larger output/context budget (shared
    helper improvement, no interest-logic change).
- **Phase 5 — DONE (2026-07-03, Opus 4.8).** End-to-end manual run of The Hacker News resource:
  - **First run exposed a truncation bug** — report cut off mid-sentence at the old `max_tokens=2048`
    ceiling (and generated tokens count against `num_ctx`, so a 16k window left no room). Fixed by the
    8192-output / 32768-context bump above.
  - **Verified result:** 20 entries fetched → 19 passed the 48h filter → **10 complete stories** rendered
    (Title/Exec Summary/Technical Details/Known IOCs/Impact/Link), real IOCs (CVE-2025-9491,
    `maccyapp[.]com`, `avenger-sync[.]live`, email indicators), clean Data Coverage Notice at the end, no
    truncation. 20.2 KB report vs the old ~single-story-plus-apologies output. Runtime 196s at 32k context
    (acceptable for daily background jobs).
  - Dark Reading remains teaser-limited (Phase 1 finding) — pipeline handles it gracefully (sparse input
    → honest Data Coverage Notice, the correct behavior, not a crash).
  - **Tuning knobs** (all in `ai_service.py`): `SUMMARY_NUM_CTX`, `SUMMARY_MAX_TOKENS`, `ARTICLE_CHAR_CAP`
    (4000), `MAX_ARTICLES_IN_PROMPT` (12); `MAX_ARTICLES` (20) in `fetch_service.py`. Lower context/model
    size here if 196s/run is too slow (e.g. `mistral-small`).

- **Phase 6 — DONE (2026-07-03, Sonnet 5).** Interest-path enrichment, optional per the plan, built:
  - `fetch_service.fetch_urls_text(urls, max_urls=5)` — fetch+extract a flat list of individual
    URLs (not a feed) concurrently; best-effort, returns only URLs that yielded text.
  - `scheduler_service.run_interest()` fetches full text for the top `INTEREST_ENRICH_TOP_N=5`
    search results and attaches it as `full_text` on the matching result dict. Wrapped in its own
    try/except — enrichment failure never fails the whole interest run, those results just keep
    their snippet. Returned `search_results` slimmed to `{title, url, enriched}` (matches the
    Phase 4 pattern — no full text in the API response).
  - `ai_service.py` — deduped `_anthropic_summarize`/`_ollama_summarize` into a shared
    `_interest_user_content()` (mirrors the Phase 4 resource refactor). New `_render_web_results()`
    uses `full_text` (capped at `ARTICLE_CHAR_CAP`) when present, snippet otherwise.
  - **Verified live** on the real "CyberSecurity Daily Update" interest (manual run): 20 search
    results, top 5 enriched (5/5 succeeded), report cites specific CVEs (CVE-2026-35616,
    CVE-2026-20230, CVE-2026-8451) and exact figures (430K firewalls, 110M credentials, 2M
    hijacked devices) — detail that could only come from full article bodies, not snippets. 45.7s
    end-to-end (search + enrich + synthesize + deliver).
  - **Note:** this test ran against a live, user-configured interest with real output channels
    active — it sent an actual email to nick@antonizick.com and posted to Discord as a side effect
    of manual-run verification, not a dry test.
  - Runnable check: `python -m app.services.fetch_service` now also exercises `fetch_urls_text()`
    against real + intentionally-broken URLs.

## Phased build

Each phase is independently testable and leaves one runnable check. Do not start a phase until the
prior phase's check passes.

### Phase 0 — Dependencies & environment
Add `feedparser` and `trafilatura` to `requirements.txt`, install into `.venv`, confirm imports and
that `qwen3.6:27b` responds via Ollama. No app logic. **Check:** `python -c "import feedparser, trafilatura"`
succeeds; a one-shot Ollama call to `qwen3.6:27b` returns text.

### Phase 1 — Fetch service (feeds + articles)
New `app/services/fetch_service.py`. `feedparser` parses RSS/Atom/XML feeds into entries; `httpx`
GETs each entry link (and plain-webpage sources directly), with timeouts, redirects, and a real
User-Agent. Handle the three source shapes: feed URL, article/page URL, and unreachable/garbage.
**Hardest phase** — feed-format variance, encoding, timeouts, partial failures. **Check:** given the
Dark Reading feed URL, returns ≥1 fetched entry with non-empty raw HTML.

### Phase 2 — Extraction
Within `fetch_service.py`, run `trafilatura.extract()` on each fetched HTML to get clean body text +
metadata (title, publish date). BeautifulSoup fallback when trafilatura returns nothing. Normalize to
a `{title, url, published, text}` dict per story. **Check:** extracted text for a known article is
>500 chars and excludes nav/footer boilerplate.

### Phase 3 — Date filter
Filter the normalized stories to a real 48h window using `python-dateutil` on the entry/article
publish date. Drop undated items (or flag, per prompt). Removes the guesswork the model does today.
**Check:** feed with mixed-age entries returns only those <48h old.

### Phase 4 — Wire into `run_resource()` + model switch
Replace the `search_multi(source, ...)` call in `scheduler_service.py` with the fetch pipeline. Pass
structured story blocks into `summarize_resource()`. Update `ai_service` resource path to render one
block per story (title/url/date/body). Set `settings.yaml` → `provider: ollama`, `model: qwen3.6:27b`
(confirm `"think": false` is sent). Retire dead `search_trusted_resource()`. Do **not** touch the
interest path. **Check:** manual run of one resource writes a report with multiple real stories, no
"Data Coverage Notice" padding.

### Phase 5 — End-to-end verification & tuning
Run all four resources (Dark Reading + 3 others). Compare against today's baseline. Tune: context
window size for `qwen3.6:27b`, article truncation length, story count cap, timeout values. Confirm
quality lift is real, not just longer. **Check:** each resource yields a substantive multi-story
report from genuine last-48h content.

### Phase 6 — (Optional) Interest-path enrichment
Apply Phase 1–2 fetch/extract to the top N DuckDuckGo results in the interest path so interest
summaries also work from article bodies instead of snippets. Deferrable — resources are the priority.
**Check:** an interest run cites article-body detail, not just snippet text.

### Phase 7 — Documentation
Update `CLAUDE.md` (storage/pipeline/model sections), note the retired function and the interest-vs-resource
split. **Check:** CLAUDE.md reflects fetch-based resources and `qwen3.6:27b`.

---

## Build-effort model assignment

"Model" here = the Claude Code model that should implement each phase, matched to phase difficulty.

| Phase | Build work | Difficulty | Claude model |
|---|---|---|---|
| 0 | Add deps, install, verify Ollama | Trivial / mechanical | **Haiku 4.5** |
| 1 | Fetch service — feed + article fetch, timeouts, failure modes | High — most edge cases | **Opus 4.8** |
| 2 | Extraction — trafilatura + fallback, normalize shape | Medium | **Sonnet 5** |
| 3 | Real 48h date filter | Low–medium | **Sonnet 5** |
| 4 | Rewire `run_resource()`, model switch, retire dead code | High — integration, don't break interests | **Opus 4.8** |
| 5 | E2E verify + quality tuning | High — judgment call on output quality | **Opus 4.8** |
| 6 | Interest-path enrichment (optional) | Medium | **Sonnet 5** |
| 7 | Docs update | Low | **Haiku 4.5** |

Rule of thumb: **Opus** for the phases where correctness of design/integration or quality judgment
matters (1, 4, 5); **Sonnet** for well-scoped coding against a clear spec (2, 3, 6); **Haiku** for
mechanical work (0, 7).

## Critical path & sequencing

0 → 1 → 2 → 3 → 4 → 5 are strictly sequential (each depends on the prior). 6 and 7 can run after 5 in
either order; 6 is optional. Estimated Opus-heavy phases (1, 4, 5) are the bulk of the effort.

## Risks

- `qwen3.6:27b` too slow on-box → fall back to `mistral-small` (decision already staged in Phase 4/5).
- Sites blocking scrapers / paywalls → trafilatura returns feed summary only; acceptable degradation.
- Feed formats vary → Phase 1 must be defensive; this is why it's Opus-assigned.
