import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def run_resource(resource_id: str, manual: bool = False) -> dict:
    """Execute a full search+summarize+output pipeline for one trusted resource."""
    from app.config import is_dev_mode
    from app.storage.markdown_store import resources_store
    from app.services.search_service import search_multi
    from app.services.ai_service import summarize_resource
    from app.services.output_service import deliver_resource_outputs
    from app.models import DEFAULT_RESOURCE_PROMPT

    if not manual and is_dev_mode():
        logger.info("Dev mode active — scheduled run suppressed for resource %s", resource_id)
        return {"resource_id": resource_id, "skipped": "dev_mode", "message": "Scheduled run suppressed: system is in development mode"}

    logger.info("Running resource: %s", resource_id)
    resource = resources_store.get(resource_id)
    if not resource:
        logger.error("Resource %s not found", resource_id)
        return {"error": "not found"}

    name = resource.get("name", "")
    source = resource.get("source", "")
    prompt_template = resource.get("_body", "") or resource.get("prompt", DEFAULT_RESOURCE_PROMPT)
    rendered_prompt = prompt_template.replace("[ SOURCE ]", source)
    schedule = resource.get("schedule", {})

    output_sent: list[str] = []
    search_results: list[dict] = []
    error = None

    try:
        search_results = await search_multi(source or name, [], schedule)
        summary = await summarize_resource(name, rendered_prompt, search_results)
        await deliver_resource_outputs(resource, summary, output_sent)
    except Exception as e:
        error = str(e)
        logger.error("Error running resource '%s': %s", name, e)

    now = datetime.now(timezone.utc).isoformat()
    resources_store.update(resource_id, {"last_run": now})

    result = {
        "resource_id": resource_id,
        "resource_name": name,
        "ran_at": now,
        "search_results": search_results,
        "output_sent": output_sent,
        "error": error,
    }
    logger.info("Completed resource '%s' — %d results, outputs: %s", name, len(search_results), output_sent)
    return result


async def run_interest(interest_id: str, manual: bool = False) -> dict:
    """Execute a full search+summarize+output pipeline for one interest."""
    from app.config import is_dev_mode
    from app.storage.markdown_store import interests_store
    from app.services.search_service import search_multi
    from app.services.ai_service import summarize_results
    from app.services.output_service import deliver_outputs

    if not manual and is_dev_mode():
        logger.info("Dev mode active — scheduled run suppressed for interest %s", interest_id)
        return {"interest_id": interest_id, "skipped": "dev_mode", "message": "Scheduled run suppressed: system is in development mode"}

    logger.info("Running interest: %s", interest_id)
    interest = interests_store.get(interest_id)
    if not interest:
        logger.error("Interest %s not found", interest_id)
        return {"error": "not found"}

    name = interest.get("name", "")
    description = interest.get("_body", "") or interest.get("description", "")
    keywords = interest.get("keywords", [])
    schedule = interest.get("schedule", {})

    output_sent: list[str] = []
    search_results: list[dict] = []
    resource_reports: list[dict] = []
    error = None

    try:
        search_results = await search_multi(name, keywords, schedule)

        # Pull pre-collected trusted resource reports (no live fetch)
        from app.services.output_service import get_recent_resource_reports
        resource_reports = get_recent_resource_reports()
        if resource_reports:
            logger.info("Enriching '%s' with %d trusted resource report(s)", name, len(resource_reports))

        summary = await summarize_results(name, description, search_results, resource_reports)
        await deliver_outputs(interest, summary, output_sent)

    except Exception as e:
        error = str(e)
        logger.error("Error running interest '%s': %s", name, e)

    now = datetime.now(timezone.utc).isoformat()
    interests_store.update(interest_id, {"last_run": now})

    result = {
        "interest_id": interest_id,
        "interest_name": name,
        "ran_at": now,
        "search_results": search_results,
        "resource_reports": len(resource_reports),
        "output_sent": output_sent,
        "error": error,
    }
    logger.info(
        "Completed interest '%s' — %d results, %d resource reports, outputs: %s",
        name, len(search_results), len(resource_reports), output_sent,
    )
    return result


def _build_trigger(schedule: dict, last_run: Optional[str] = None):
    stype = schedule.get("type", "interval")
    run_time = schedule.get("run_time", "09:00")
    hour, minute = (int(x) for x in run_time.split(":"))

    if stype == "manual":
        return None

    if stype == "weekly":
        days = schedule.get("days_of_week", [0])
        day_str = ",".join(str(d) for d in days)
        return CronTrigger(day_of_week=day_str, hour=hour, minute=minute, timezone="UTC")

    if stype == "cron":
        expr = schedule.get("cron_expression", "0 9 * * *")
        parts = expr.strip().split()
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4], timezone="UTC",
            )

    # Interval: anchor to last_run so reboots don't reset the clock.
    # APScheduler computes next_fire = last_run + N*interval (smallest N in future).
    unit = schedule.get("interval_unit", "days")
    value = int(schedule.get("interval_value", 1))
    kwargs: dict = {unit: value}
    if last_run:
        try:
            start = datetime.fromisoformat(last_run)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            kwargs["start_date"] = start
        except Exception:
            pass
    return IntervalTrigger(**kwargs)


def schedule_interest(interest: dict) -> None:
    scheduler = get_scheduler()
    interest_id = interest["id"]
    job_id = f"interest_{interest_id}"

    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None

    if not interest.get("active", True):
        logger.info("Interest %s is inactive — not scheduling", interest_id)
        return

    schedule_cfg = interest.get("schedule", {})
    trigger = _build_trigger(schedule_cfg, last_run=interest.get("last_run"))
    if trigger is None:
        logger.info("Interest %s set to manual — not scheduling", interest_id)
        return

    scheduler.add_job(
        run_interest,
        trigger=trigger,
        id=job_id,
        args=[interest_id],
        replace_existing=True,
        name=interest.get("name", interest_id),
    )
    job = scheduler.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    if next_run:
        from app.storage.markdown_store import interests_store
        interests_store.update(interest_id, {"next_run": next_run})
    logger.info("Scheduled '%s' (%s), next run: %s", interest.get("name"), job_id, next_run)


def unschedule_interest(interest_id: str) -> None:
    scheduler = get_scheduler()
    job_id = f"interest_{interest_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled %s", job_id)


def schedule_resource(resource: dict) -> None:
    scheduler = get_scheduler()
    resource_id = resource["id"]
    job_id = f"resource_{resource_id}"

    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None

    if not resource.get("active", True):
        logger.info("Resource %s is inactive — not scheduling", resource_id)
        return

    schedule_cfg = resource.get("schedule", {})
    trigger = _build_trigger(schedule_cfg, last_run=resource.get("last_run"))
    if trigger is None:
        logger.info("Resource %s set to manual — not scheduling", resource_id)
        return

    scheduler.add_job(
        run_resource,
        trigger=trigger,
        id=job_id,
        args=[resource_id],
        replace_existing=True,
        name=resource.get("name", resource_id),
    )
    job = scheduler.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    if next_run:
        from app.storage.markdown_store import resources_store
        resources_store.update(resource_id, {"next_run": next_run})
    logger.info("Scheduled resource '%s' (%s), next run: %s", resource.get("name"), job_id, next_run)


def unschedule_resource(resource_id: str) -> None:
    scheduler = get_scheduler()
    job_id = f"resource_{resource_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled %s", job_id)


def schedule_summary_report(report: dict) -> None:
    scheduler = get_scheduler()
    report_id = report["id"]
    job_id = f"summary_{report_id}"

    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None

    if not report.get("active", True):
        logger.info("Summary report %s is inactive — not scheduling", report_id)
        return

    schedule_cfg = report.get("schedule", {})
    trigger = _build_trigger(schedule_cfg, last_run=report.get("last_run"))
    if trigger is None:
        logger.info("Summary report %s set to manual — not scheduling", report_id)
        return

    from app.services.summary_service import run_summary_report
    scheduler.add_job(
        run_summary_report,
        trigger=trigger,
        id=job_id,
        args=[report_id],
        replace_existing=True,
        name=report.get("name", report_id),
    )
    job = scheduler.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    if next_run:
        from app.storage.markdown_store import summary_reports_store
        summary_reports_store.update(report_id, {"next_run": next_run})
    logger.info("Scheduled summary '%s' (%s), next run: %s", report.get("name"), job_id, next_run)


def unschedule_summary_report(report_id: str) -> None:
    scheduler = get_scheduler()
    job_id = f"summary_{report_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled %s", job_id)


def clear_user_schedules() -> int:
    """Remove all interest, resource, and summary jobs. Leaves system jobs (ioc_*) intact."""
    scheduler = get_scheduler()
    removed = 0
    for job in scheduler.get_jobs():
        if job.id.startswith(("interest_", "resource_", "summary_")):
            scheduler.remove_job(job.id)
            removed += 1
    logger.info("Cleared %d user-scheduled jobs", removed)
    return removed


def reload_all_schedules() -> None:
    from app.storage.markdown_store import interests_store, summary_reports_store, resources_store
    interests = interests_store.list()
    for interest in interests:
        schedule_interest(interest)
    summaries = summary_reports_store.list()
    for report in summaries:
        schedule_summary_report(report)
    resources = resources_store.list()
    for resource in resources:
        schedule_resource(resource)
    logger.info(
        "Reloaded schedules for %d interests, %d summary reports, %d resources",
        len(interests), len(summaries), len(resources),
    )


def list_jobs() -> list[dict]:
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs


class SchedulerService:
    async def start(self) -> None:
        scheduler = get_scheduler()
        scheduler.start()
        reload_all_schedules()
        logger.info("Scheduler started")

    async def stop(self) -> None:
        scheduler = get_scheduler()
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
