import logging
from typing import Optional
from app.config import get_config

logger = logging.getLogger(__name__)


# Ollama's default context window is ~4k tokens; anything beyond it is SILENTLY dropped from
# the prompt. We feed full article text (many KB), and the model's own generated tokens ALSO
# count against num_ctx — so the window must hold input + output. A multi-story brief (the
# resource prompt asks for 8-15 stories) needs a large output budget, hence 32k context + a
# generous num_predict. Small/one-off calls (connection test) keep the modest default so we
# don't load the 27B model at full context for a two-token reply.
OLLAMA_NUM_CTX = 8192            # default for small calls
SUMMARY_NUM_CTX = 32768         # context window for report synthesis (input + output)
SUMMARY_MAX_TOKENS = 8192       # output budget for a full multi-story report

# Per-article truncation and count caps applied before building the prompt, so a handful of long
# articles can't blow past the context window.
ARTICLE_CHAR_CAP = 4000
MAX_ARTICLES_IN_PROMPT = 12


async def _ollama_chat(
    base_url: str,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int = 2048,
    num_ctx: int = OLLAMA_NUM_CTX,
) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "stream": False,
                # Reasoning models burn the token budget on hidden chain-of-thought before
                # any visible reply, which can truncate the actual report to nothing —
                # disable it since we only need the final structured text.
                "think": False,
                "options": {"num_predict": max_tokens, "num_ctx": num_ctx},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


def _render_article_blocks(stories: list[dict]) -> str:
    """Render fetched articles (Phase 1-3 story dicts) into the prompt body.

    Each story: {title, url, published, text}. Applies count + per-article length caps so the
    payload fits the model context window. Full article text (not search snippets) is what makes
    the downstream report substantive.
    """
    block = "\n\n## FETCHED ARTICLES (full text from the source)\n"
    for s in stories[:MAX_ARTICLES_IN_PROMPT]:
        published = s.get("published") or "date unknown"
        text = (s.get("text") or "").strip()
        if len(text) > ARTICLE_CHAR_CAP:
            text = text[:ARTICLE_CHAR_CAP] + "\n…[truncated]"
        block += (
            f"\n### {s.get('title', '')}\n"
            f"URL: {s.get('url', '')}\n"
            f"Published: {published}\n\n"
            f"{text}\n\n---\n"
        )
    return block


async def list_ollama_models(base_url: str) -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}

SYSTEM_PROMPT = """You are Nx-Citadel's research assistant. Your ONLY sources of information \
are the web search results and trusted resource reports provided by the user. You MUST NOT \
supplement, fill in, or infer details from your training data — if something is not in the \
provided material, say so explicitly rather than inventing or recalling it.

Rules you must follow without exception:
1. Every factual claim in your report MUST be traceable to a specific provided source — a web \
   search result or a trusted resource report. Cite the source name/URL and date on every claim.
2. If a result's snippet does not contain a date, note the source and mark it "date unknown."
3. If the search results are sparse or outdated, state that clearly at the top of the report \
   rather than supplementing with background knowledge. Do not silently pad the report.
4. Mark any claim that appears in only one source as "(single source — verify independently)."
5. For trusted resource reports: only incorporate content that is genuinely relevant to the \
   interest topic. Clearly attribute each piece of information to its source monitor name.
6. Do NOT use phrases like "as of my knowledge" or draw on anything outside the provided material.

Your output structure: concise Markdown with clear headings, source citations on every claim, \
and a prominent "Data Coverage" note at the top stating the date range of the provided results."""


async def summarize_results(
    interest_name: str,
    description: str,
    results: list[dict],
    resource_reports: list[dict],
) -> str:
    config = get_config()
    if config.llm.provider != "ollama" and not config.llm.api_key:
        return _fallback_summary(interest_name, results, resource_reports)

    if config.llm.provider == "anthropic":
        return await _anthropic_summarize(interest_name, description, results, resource_reports, config)
    if config.llm.provider == "ollama":
        return await _ollama_summarize(interest_name, description, results, resource_reports, config)

    return _fallback_summary(interest_name, results, resource_reports)


def _render_web_results(results: list[dict]) -> str:
    """Render web search results — full fetched article text where Phase 6 enrichment
    succeeded (result carries `full_text`), snippet otherwise."""
    block = "\n\n## WEB SEARCH RESULTS\n"
    for r in results:
        block += f"\n**{r['title']}** ({r['url']})\n"
        text = (r.get("full_text") or "").strip()
        if text:
            if len(text) > ARTICLE_CHAR_CAP:
                text = text[:ARTICLE_CHAR_CAP] + "\n…[truncated]"
            block += f"{text}\n"
        else:
            block += f"{r['snippet']}\n"
    return block


def _interest_user_content(interest_name: str, description: str, results: list[dict], resource_reports: list[dict]) -> str:
    resource_block = ""
    if resource_reports:
        resource_block = (
            "\n\n## TRUSTED RESOURCE REPORTS (pre-collected, AI-analyzed)\n"
            "These are summaries from trusted source monitors collected before this run. "
            "Only incorporate content that is directly relevant to the interest topic.\n"
        )
        for r in resource_reports:
            resource_block += (
                f"\n### Source Monitor: {r['resource_name']} | Collected: {r['ran_at']}\n"
                f"{r['content']}\n---\n"
            )

    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Report generated: {now_str}\n"
        f"Interest topic: **{interest_name}**\n"
        f"User instructions: {description}\n"
        f"{resource_block}{_render_web_results(results)}\n\n"
        "Using ONLY the material above (no training data), produce the report "
        "the user requested. Begin with a 'Data Coverage' line showing the date range "
        "of the results you are drawing from. Cite source + date on every claim. "
        "If trusted resource content is included, attribute it to the source monitor name."
    )


async def _anthropic_summarize(
    interest_name: str,
    description: str,
    results: list[dict],
    resource_reports: list[dict],
    config,
) -> str:
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.llm.api_key)
        user_content = _interest_user_content(interest_name, description, results, resource_reports)

        message = await client.messages.create(
            model=config.llm.model,
            max_tokens=SUMMARY_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        summary = message.content[0].text
        logger.info("AI summary generated for '%s' (%d chars)", interest_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Anthropic summarize failed: %s", e)
        return _fallback_summary(interest_name, results, resource_reports)


async def _ollama_summarize(
    interest_name: str,
    description: str,
    results: list[dict],
    resource_reports: list[dict],
    config,
) -> str:
    try:
        user_content = _interest_user_content(interest_name, description, results, resource_reports)
        summary = await _ollama_chat(
            config.llm.ollama_base_url, config.llm.model, SYSTEM_PROMPT, user_content,
            max_tokens=SUMMARY_MAX_TOKENS, num_ctx=SUMMARY_NUM_CTX,
        )
        logger.info("AI summary generated for '%s' via Ollama (%d chars)", interest_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Ollama summarize failed: %s", e)
        return _fallback_summary(interest_name, results, resource_reports)


def _fallback_summary(interest_name: str, results: list[dict], resource_reports: list[dict]) -> str:
    lines = [f"# Report: {interest_name}\n"]
    if resource_reports:
        lines.append("## Trusted Resource Reports\n")
        for r in resource_reports:
            lines.append(f"### {r['resource_name']} — {r['ran_at']}\n{r['content'][:500]}\n---\n")
    if results:
        lines.append("## Web Results\n")
        for r in results:
            lines.append(f"- [{r['title']}]({r['url']})\n  {r['snippet'][:200]}\n")
    lines.append("\n_No LLM API key configured — raw results shown above._")
    return "\n".join(lines)


async def summarize_resource(resource_name: str, rendered_prompt: str, stories: list[dict]) -> str:
    """Summarize fetched articles (Phase 1-3 story dicts: {title, url, published, text})."""
    config = get_config()
    if config.llm.provider != "ollama" and not config.llm.api_key:
        return _fallback_resource_summary(resource_name, stories)

    if config.llm.provider == "anthropic":
        return await _anthropic_summarize_resource(resource_name, rendered_prompt, stories, config)
    if config.llm.provider == "ollama":
        return await _ollama_summarize_resource(resource_name, rendered_prompt, stories, config)

    return _fallback_resource_summary(resource_name, stories)


def _resource_user_content(resource_name: str, rendered_prompt: str, stories: list[dict]) -> str:
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Report generated: {now_str}\n"
        f"Source monitor: **{resource_name}**\n"
        f"User query / instructions: {rendered_prompt}\n"
        f"{_render_article_blocks(stories)}\n\n"
        "Using ONLY the fetched articles above (no training data), follow the user's instructions. "
        "Each article already carries its publish date and URL — cite them on every claim. "
        "If the fetched articles are sparse, state that clearly rather than padding with background knowledge."
    )


async def _anthropic_summarize_resource(
    resource_name: str,
    rendered_prompt: str,
    stories: list[dict],
    config,
) -> str:
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.llm.api_key)
        user_content = _resource_user_content(resource_name, rendered_prompt, stories)

        message = await client.messages.create(
            model=config.llm.model,
            max_tokens=SUMMARY_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        summary = message.content[0].text
        logger.info("Resource summary generated for '%s' (%d chars)", resource_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Anthropic resource summarize failed: %s", e)
        return _fallback_resource_summary(resource_name, stories)


async def _ollama_summarize_resource(
    resource_name: str,
    rendered_prompt: str,
    stories: list[dict],
    config,
) -> str:
    try:
        user_content = _resource_user_content(resource_name, rendered_prompt, stories)
        summary = await _ollama_chat(
            config.llm.ollama_base_url, config.llm.model, SYSTEM_PROMPT, user_content,
            max_tokens=SUMMARY_MAX_TOKENS, num_ctx=SUMMARY_NUM_CTX,
        )
        logger.info("Resource summary generated for '%s' via Ollama (%d chars)", resource_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Ollama resource summarize failed: %s", e)
        return _fallback_resource_summary(resource_name, stories)


def _fallback_resource_summary(resource_name: str, stories: list[dict]) -> str:
    lines = [f"# Resource Report: {resource_name}\n"]
    if stories:
        lines.append("## Fetched Articles\n")
        for s in stories:
            lines.append(f"- [{s.get('title','')}]({s.get('url','')})\n  {(s.get('text','') or '')[:200]}\n")
    lines.append("\n_No LLM API key configured — raw fetched articles shown above._")
    return "\n".join(lines)


async def test_connection(provider: str, api_key: str, model: str, ollama_base_url: str = "") -> dict:
    if provider == "anthropic":
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model=model,
                max_tokens=20,
                messages=[{"role": "user", "content": "Reply with: OK"}],
            )
            return {"ok": True, "response": msg.content[0].text}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if provider == "ollama":
        try:
            # Reasoning models (e.g. qwen3.5) spend tokens on hidden "thinking" before
            # the visible reply, so a small budget can truncate before any content lands.
            response = await _ollama_chat(ollama_base_url, model, "You are a connection test.", "Reply with: OK", max_tokens=200)
            return {"ok": True, "response": response or "(connected — model returned no visible content)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"Provider '{provider}' not supported"}
