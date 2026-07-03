"""Summary report execution: collect matching interest reports + trusted resources, synthesize."""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.services.output_service import _ts_from_filename

logger = logging.getLogger(__name__)

INTEREST_REPORTS_DIR = Path("data/reports")

SUMMARY_SYSTEM_PROMPT = """You are Nx-Citadel's synthesis engine. Your job is to read a set of \
intelligence reports collected over a defined time window and produce a single coherent executive \
summary. Your ONLY source of information is the provided reports and trusted resource data.

Rules you must follow without exception:
1. Base every claim ONLY on the provided material — no training-data fill-in.
2. Cite the source interest name and report date for every key claim.
3. Identify cross-report patterns, convergences, or contradictions and call them out explicitly.
4. If reports are sparse or the time window produced few results, say so — do not pad.
5. Structure your output as: Data Coverage → Key Findings → Cross-Topic Patterns → \
Trusted Source Highlights → Conclusion.
6. Tone: analytical and neutral. No speculation beyond what the sources support."""


def _lookback_delta(schedule: dict) -> timedelta:
    stype = schedule.get("type", "interval")
    if stype == "weekly":
        return timedelta(weeks=1)
    if stype in ("cron", "manual"):
        return timedelta(days=1)
    unit = schedule.get("interval_unit", "days")
    value = int(schedule.get("interval_value", 1))
    seconds = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}.get(unit, 86400) * value
    return timedelta(seconds=seconds)


async def run_summary_report(report_id: str, manual: bool = False) -> dict:
    from app.config import is_dev_mode
    from app.storage.markdown_store import summary_reports_store, interests_store
    from app.services.output_service import deliver_summary_outputs

    if not manual and is_dev_mode():
        logger.info("Dev mode active — scheduled run suppressed for summary report %s", report_id)
        return {"report_id": report_id, "skipped": "dev_mode", "message": "Scheduled run suppressed: system is in development mode"}

    logger.info("Running summary report: %s", report_id)
    report = summary_reports_store.get(report_id)
    if not report:
        logger.error("Summary report %s not found", report_id)
        return {"error": "not found"}

    name = report.get("name", "")
    description = report.get("_body", "") or report.get("description", "")
    tags = set(report.get("tags", []))
    schedule = report.get("schedule", {})

    delta = _lookback_delta(schedule)
    cutoff = datetime.now(timezone.utc) - delta

    output_sent: list[str] = []
    collected_reports: list[dict] = []
    resource_reports: list[dict] = []
    error = None

    try:
        # Collect matching interest reports within lookback window
        all_interests = {i["id"]: i for i in interests_store.list()}

        if INTEREST_REPORTS_DIR.exists():
            for interest_dir in INTEREST_REPORTS_DIR.iterdir():
                if not interest_dir.is_dir():
                    continue
                interest = all_interests.get(interest_dir.name)
                if not interest:
                    continue

                # Tag filter: if summary specifies tags, interest must share at least one
                if tags:
                    interest_tags = set(interest.get("tags", []))
                    if not tags.intersection(interest_tags):
                        continue

                interest_name = interest.get("name", interest_dir.name)
                for report_file in sorted(interest_dir.glob("*.md"), reverse=True):
                    file_ts = _ts_from_filename(report_file)
                    if file_ts < cutoff:
                        continue
                    try:
                        content = report_file.read_text(encoding="utf-8")
                        if content.startswith("---"):
                            end = content.find("---", 3)
                            if end != -1:
                                content = content[end + 3:].lstrip("\n")
                        collected_reports.append({
                            "interest_name": interest_name,
                            "filename": report_file.name,
                            "ran_at": file_ts.isoformat(),
                            "content": content[:3000],
                        })
                    except Exception as e:
                        logger.warning("Failed to read report %s: %s", report_file, e)

        # Pull pre-collected trusted resource reports (no live fetch)
        from app.services.output_service import get_recent_resource_reports
        resource_reports = get_recent_resource_reports(tags=tags if tags else None)
        if resource_reports:
            logger.info("Enriching summary '%s' with %d trusted resource report(s)", name, len(resource_reports))

        summary = await _synthesize(name, description, collected_reports, resource_reports)
        await deliver_summary_outputs(report, summary, output_sent)

    except Exception as e:
        error = str(e)
        logger.error("Error running summary report '%s': %s", name, e)

    now = datetime.now(timezone.utc).isoformat()
    summary_reports_store.update(report_id, {"last_run": now})

    result = {
        "report_id": report_id,
        "report_name": name,
        "ran_at": now,
        "reports_collected": len(collected_reports),
        "trusted_sources": len(resource_reports),
        "output_sent": output_sent,
        "error": error,
    }
    logger.info(
        "Completed summary report '%s' — %d source reports, %d resource reports, outputs: %s",
        name, len(collected_reports), len(resource_reports), output_sent,
    )
    return result


async def _synthesize(
    summary_name: str,
    description: str,
    collected_reports: list[dict],
    resource_reports: list[dict],
) -> str:
    from app.config import get_config
    config = get_config()
    if config.llm.provider != "ollama" and not config.llm.api_key:
        return _fallback(summary_name, collected_reports, resource_reports)
    if config.llm.provider == "anthropic":
        return await _anthropic_synthesize(summary_name, description, collected_reports, resource_reports, config)
    if config.llm.provider == "ollama":
        return await _ollama_synthesize(summary_name, description, collected_reports, resource_reports, config)
    return _fallback(summary_name, collected_reports, resource_reports)


async def _anthropic_synthesize(
    summary_name: str,
    description: str,
    collected_reports: list[dict],
    resource_reports: list[dict],
    config,
) -> str:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.llm.api_key)

        resource_block = ""
        if resource_reports:
            resource_block = (
                "\n\n## TRUSTED RESOURCE REPORTS (pre-collected AI summaries)\n"
                "Each section is a recent AI-analyzed summary from a trusted source monitor. "
                "Incorporate content that is relevant to the summary topic and call out cross-topic patterns.\n"
            )
            for r in resource_reports:
                resource_block += (
                    f"\n### Source Monitor: {r['resource_name']} | Collected: {r['ran_at']}\n"
                    f"{r['content']}\n---\n"
                )

        reports_block = ""
        if collected_reports:
            reports_block = f"\n\n## COLLECTED INTELLIGENCE REPORTS ({len(collected_reports)} reports)\n"
            for r in collected_reports:
                reports_block += (
                    f"\n### Interest: {r['interest_name']} | Collected: {r['ran_at']}\n"
                    f"{r['content']}\n---\n"
                )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_content = (
            f"Summary report generated: {now_str}\n"
            f"Summary name: **{summary_name}**\n"
            f"User instructions: {description}\n"
            f"{resource_block}{reports_block}\n\n"
            "Using ONLY the material above, produce the executive summary. Begin with a "
            "'Data Coverage' line stating the date range and number of source reports included. "
            "If trusted resource reports are present, include a 'Trusted Source Highlights' section "
            "attributing each finding to its source monitor name."
        )

        message = await client.messages.create(
            model=config.llm.model,
            max_tokens=3000,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        text = message.content[0].text
        logger.info("AI synthesis generated for '%s' (%d chars)", summary_name, len(text))
        return text
    except Exception as e:
        logger.error("Anthropic synthesis failed: %s", e)
        return _fallback(summary_name, collected_reports, resource_reports)


async def _ollama_synthesize(
    summary_name: str,
    description: str,
    collected_reports: list[dict],
    resource_reports: list[dict],
    config,
) -> str:
    from app.services.ai_service import _ollama_chat
    try:
        resource_block = ""
        if resource_reports:
            resource_block = (
                "\n\n## TRUSTED RESOURCE REPORTS (pre-collected AI summaries)\n"
                "Each section is a recent AI-analyzed summary from a trusted source monitor. "
                "Incorporate content that is relevant to the summary topic and call out cross-topic patterns.\n"
            )
            for r in resource_reports:
                resource_block += (
                    f"\n### Source Monitor: {r['resource_name']} | Collected: {r['ran_at']}\n"
                    f"{r['content']}\n---\n"
                )

        reports_block = ""
        if collected_reports:
            reports_block = f"\n\n## COLLECTED INTELLIGENCE REPORTS ({len(collected_reports)} reports)\n"
            for r in collected_reports:
                reports_block += (
                    f"\n### Interest: {r['interest_name']} | Collected: {r['ran_at']}\n"
                    f"{r['content']}\n---\n"
                )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_content = (
            f"Summary report generated: {now_str}\n"
            f"Summary name: **{summary_name}**\n"
            f"User instructions: {description}\n"
            f"{resource_block}{reports_block}\n\n"
            "Using ONLY the material above, produce the executive summary. Begin with a "
            "'Data Coverage' line stating the date range and number of source reports included. "
            "If trusted resource reports are present, include a 'Trusted Source Highlights' section "
            "attributing each finding to its source monitor name."
        )

        text = await _ollama_chat(config.llm.ollama_base_url, config.llm.model, SUMMARY_SYSTEM_PROMPT, user_content, max_tokens=3000)
        logger.info("AI synthesis generated for '%s' via Ollama (%d chars)", summary_name, len(text))
        return text
    except Exception as e:
        logger.error("Ollama synthesis failed: %s", e)
        return _fallback(summary_name, collected_reports, resource_reports)


def _fallback(
    summary_name: str,
    collected_reports: list[dict],
    resource_reports: list[dict],
) -> str:
    lines = [f"# Summary Report: {summary_name}\n"]
    if not collected_reports and not resource_reports:
        lines.append("_No matching reports or trusted resources found for this time window._")
        return "\n".join(lines)
    if resource_reports:
        lines.append("## Trusted Resource Reports\n")
        for r in resource_reports:
            lines.append(f"### {r['resource_name']} — {r['ran_at']}\n{r['content'][:500]}\n---\n")
    if collected_reports:
        lines.append(f"## Source Reports ({len(collected_reports)} collected)\n")
        for r in collected_reports:
            lines.append(f"### {r['interest_name']} — {r['ran_at']}\n{r['content'][:500]}\n---\n")
    lines.append("\n_No LLM API key configured — raw collected content shown above._")
    return "\n".join(lines)
