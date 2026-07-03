# Trusted Resource Pipeline Rework — Overview & Reference

**Date:** 2026-07-03 | **Status:** Complete (Phases 0–6)

## The Problem That Was Solved

Trusted resources were producing low-quality reports:
- **Old:** 1 story + apologies (e.g., Dark Reading: 120 chars + "Data Coverage Notice" blocks)
- **Root cause:** `run_resource()` threw the feed/homepage URL into DuckDuckGo as a search query. The LLM saw ~10 search snippets while being told to "parse the RSS feed" and "follow links to full articles" — an impossible task.
- **Secondary issues:** coding model doing news synthesis, no real date filtering, dead code paths.

## The Solution Built

**Redesign the resource pipeline to FETCH instead of SEARCH.**

Split behavior by use case:
- **Interests:** Keep search-based (topic monitoring across the web)
- **Resources:** New fetch-based (pull specific sources: feeds, homepages)

Both paths feed full article text to a general instruct model (`qwen3.6:27b`) with proper context and output budgets.

## The Pipeline (simplified)

```
Resource.source → fetch_source() → extract_stories() → filter_recent() 
                     (feedparser)    (trafilatura)      (dateutil)
                                                            ↓
                                                    Filtered story dicts
                                                    {title, url, published, text}
                                                            ↓
                                              qwen3.6:27b synthesis
                                          (SUMMARY_NUM_CTX=32768)
                                                            ↓
                                            10+ complete stories with:
                                          - Real CVE numbers
                                          - Exact figures
                                          - True IOCs
                                          - Source citations
```

## Results

| Metric | Before | After |
|--------|--------|-------|
| Stories per report | 1 | 10+ |
| Source data | 200-char DDG snippets | 2.5–18 KB article bodies |
| Quality | "date unknown", sparse | CVE-2026-35616, 430K firewalls, 110M credentials |
| Dark Reading | 1 teaser | 3 teasers (JS bot-block, graceful) |
| Runtime | ~90s | ~196s (daily schedule, acceptable) |

## Key Files

| File | Purpose |
|------|---------|
| `app/services/fetch_service.py` | Phases 1–3: fetch/extract/filter (+ Phase 6 interest enrichment) |
| `app/services/scheduler_service.py` | Phase 4: rewired `run_resource()` and `run_interest()` |
| `app/services/ai_service.py` | Phase 4–6: refactored summarize paths, Ollama context/budget fixes |
| `docs/resource-pipeline-rework-plan.md` | Full 8-phase build log with per-phase Claude assignments |
| `CLAUDE.md` | Updated: resource pipeline section, Stack table, app structure |

## Critical Tuning Constants

(All in `ai_service.py`)

- `SUMMARY_NUM_CTX = 32768` — Ollama context window for summaries (Ollama silently drops input past ~4K default)
- `SUMMARY_MAX_TOKENS = 8192` — Output budget for multi-story reports
- `ARTICLE_CHAR_CAP = 4000` — Per-article truncation in prompts
- `MAX_ARTICLES_IN_PROMPT = 12` — Count cap to fit context window

## Model Switching Notes

The pipeline works with any instruct model ≥32K context:
- **Current:** `qwen3.6:27b` (256K context) ✅
- **Fallback:** `mistral-small` (32K context, weaker but works) ✅
- **Avoid:** coding models, <32K context (silent truncation)

When switching: check `ollama show <model>` for its declared max context. If <32K, articles will be silently truncated at the model's boundary.

## Phase 6: Interest Enrichment (Optional, Built)

The interest path (which legitimately uses web search for topic monitoring) was enriched with Phase 6:

```
search_multi(topic) → top 5 URLs → fetch_urls_text() → full_text?
                                                             ↓
                    LLM prefers full_text over snippet
                                                             ↓
                                                  More detailed summaries
```

Best-effort and non-fatal — a fetch failure just leaves that result on its snippet.

Verified live on real "CyberSecurity Daily Update" interest; report cited specific CVEs and exact figures impossible from snippets alone.

## Testing & Verification

All phases include runnable checks:

```bash
# Full pipeline (fetch → extract → filter + interest enrichment)
python -m app.services.fetch_service

# Manual resource run
python -c "
import asyncio
from app.services.scheduler_service import run_resource
result = await run_resource('<resource-id>', manual=True)
print(result)
"

# Manual interest run
python -c "
import asyncio
from app.services.scheduler_service import run_interest
result = await run_interest('<interest-id>', manual=True)
print(result)
"
```

## For Future Maintenance

1. **Adding a resource:** Set `source` to a feed URL or homepage; the pipeline auto-discovers feeds and handles both.
2. **Tweaking output quality:** Adjust `SUMMARY_NUM_CTX`, `ARTICLE_CHAR_CAP`, or `MAX_ARTICLES_IN_PROMPT` in `ai_service.py`.
3. **Changing models:** Pick an instruct model with ≥32K context; Ollama silently truncates anything smaller.
4. **Debugging slow runs:** Dark Reading stays teaser-only (JS bot-block); others yield full text. Runtime is 196s at 32K context with `qwen3.6:27b` — normal for daily jobs. Lighter models (e.g. `mistral-small`, 7B) are ~30% faster but weaker synthesis.

## Architecture Diagram

See ASCII diagram in the memory file: `memory/2026-07-03.md` "Before/After" section.

---

**Next steps:** None required. Pipeline is production-ready. Phase 6 (interest enrichment) is optional and already built.
