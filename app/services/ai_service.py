import logging
from typing import Optional
from app.config import get_config

logger = logging.getLogger(__name__)

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
    if not config.llm.api_key:
        return _fallback_summary(interest_name, results, resource_reports)

    if config.llm.provider == "anthropic":
        return await _anthropic_summarize(interest_name, description, results, resource_reports, config)

    return _fallback_summary(interest_name, results, resource_reports)


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

        web_block = "\n\n## WEB SEARCH RESULTS\n"
        for r in results:
            web_block += f"\n**{r['title']}** ({r['url']})\n{r['snippet']}\n"

        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_content = (
            f"Report generated: {now_str}\n"
            f"Interest topic: **{interest_name}**\n"
            f"User instructions: {description}\n"
            f"{resource_block}{web_block}\n\n"
            "Using ONLY the material above (no training data), produce the report "
            "the user requested. Begin with a 'Data Coverage' line showing the date range "
            "of the results you are drawing from. Cite source + date on every claim. "
            "If trusted resource content is included, attribute it to the source monitor name."
        )

        message = await client.messages.create(
            model=config.llm.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        summary = message.content[0].text
        logger.info("AI summary generated for '%s' (%d chars)", interest_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Anthropic summarize failed: %s", e)
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


async def summarize_resource(resource_name: str, rendered_prompt: str, results: list[dict]) -> str:
    config = get_config()
    if not config.llm.api_key:
        return _fallback_resource_summary(resource_name, results)

    if config.llm.provider == "anthropic":
        return await _anthropic_summarize_resource(resource_name, rendered_prompt, results, config)

    return _fallback_resource_summary(resource_name, results)


async def _anthropic_summarize_resource(
    resource_name: str,
    rendered_prompt: str,
    results: list[dict],
    config,
) -> str:
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.llm.api_key)

        web_block = "\n\n## WEB SEARCH RESULTS\n"
        for r in results:
            web_block += f"\n**{r['title']}** ({r['url']})\n{r['snippet']}\n"

        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_content = (
            f"Report generated: {now_str}\n"
            f"Source monitor: **{resource_name}**\n"
            f"User query: {rendered_prompt}\n"
            f"{web_block}\n\n"
            "Using ONLY the search results above (no training data), answer the user query. "
            "Begin with a 'Data Coverage' line showing the date range of the results. "
            "Cite source URL and date on every claim. "
            "If results are sparse, state that clearly rather than padding with background knowledge."
        )

        message = await client.messages.create(
            model=config.llm.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        summary = message.content[0].text
        logger.info("Resource summary generated for '%s' (%d chars)", resource_name, len(summary))
        return summary
    except Exception as e:
        logger.error("Anthropic resource summarize failed: %s", e)
        return _fallback_resource_summary(resource_name, results)


def _fallback_resource_summary(resource_name: str, results: list[dict]) -> str:
    lines = [f"# Resource Report: {resource_name}\n"]
    if results:
        lines.append("## Web Results\n")
        for r in results:
            lines.append(f"- [{r['title']}]({r['url']})\n  {r['snippet'][:200]}\n")
    lines.append("\n_No LLM API key configured — raw results shown above._")
    return "\n".join(lines)


async def test_connection(provider: str, api_key: str, model: str) -> dict:
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
    return {"ok": False, "error": f"Provider '{provider}' not supported"}
