import logging
import aiofiles
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("data/reports")
SUMMARY_REPORTS_DIR = Path("data/summary_reports")
RESOURCE_REPORTS_DIR = Path("data/resource_reports")


def _ts_from_filename(path: Path) -> datetime:
    """Parse run timestamp from filename like '2026-04-22_103045.md'.
    Falls back to st_mtime only if the name doesn't match (shouldn't happen)."""
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


async def deliver_outputs(interest: dict, summary: str, output_sent: list[str]) -> None:
    output_cfg = interest.get("output", {})
    types = output_cfg.get("types", ["report"])

    path = await save_report(interest["id"], interest["name"], summary)
    output_sent.append(f"report:{path}")

    if "email" in types:
        recipients = output_cfg.get("email_recipients", [])
        if recipients:
            ok = await send_email(recipients, interest["name"], summary)
            output_sent.append("email:ok" if ok else "email:failed")

    if "slack" in types:
        webhook = output_cfg.get("slack_webhook") or _get_default_slack_webhook()
        if webhook:
            ok = await send_slack(webhook, interest["name"], summary)
            output_sent.append("slack:ok" if ok else "slack:failed")

    if "sms" in types:
        numbers = output_cfg.get("sms_numbers", [])
        if numbers:
            ok = await send_sms(numbers, interest["name"], summary)
            output_sent.append("sms:ok" if ok else "sms:failed")

    if "discord" in types:
        webhook = output_cfg.get("discord_webhook") or _get_default_discord_webhook()
        if webhook:
            ok = await send_discord(webhook, interest["name"], summary)
            output_sent.append("discord:ok" if ok else "discord:failed")


async def save_report(interest_id: str, name: str, content: str) -> str:
    now = datetime.now(timezone.utc)
    report_dir = REPORTS_DIR / interest_id
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    path = report_dir / filename
    header = f"---\ninterest_id: {interest_id}\nname: {name}\ngenerated_at: {now.isoformat()}\n---\n\n"
    async with aiofiles.open(path, "w") as f:
        await f.write(header + content)
    logger.info("Report saved: %s", path)
    return str(path)


async def send_email(recipients: list[str], subject: str, body_md: str) -> bool:
    from app.config import get_config
    cfg = get_config().email
    if not cfg.smtp_host or not cfg.from_address:
        logger.warning("Email not configured — skipping")
        return False
    try:
        import aiosmtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = cfg.from_address
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"Nx-Citadel Report: {subject}"
        msg.set_content(body_md)
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user or None,
            password=cfg.smtp_password or None,
            start_tls=cfg.use_tls,
        )
        logger.info("Email sent to %s for '%s'", recipients, subject)
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


async def send_slack(webhook_url: str, name: str, summary: str) -> bool:
    import httpx
    try:
        text = f"*Nx-Citadel Report: {name}*\n\n{summary[:2900]}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"text": text})
        ok = resp.status_code == 200
        logger.info("Slack send '%s': %s", name, "ok" if ok else resp.text)
        return ok
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return False


async def send_sms(numbers: list[str], name: str, summary: str) -> bool:
    from app.config import get_config
    cfg = get_config().sms
    if not cfg.account_sid or not cfg.auth_token:
        logger.warning("SMS not configured — skipping")
        return False
    try:
        import httpx, base64
        text = f"Nx-Citadel: {name}\n{summary[:140]}"
        auth = base64.b64encode(f"{cfg.account_sid}:{cfg.auth_token}".encode()).decode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
        async with httpx.AsyncClient(timeout=10) as client:
            for number in numbers:
                await client.post(
                    url,
                    data={"From": cfg.from_number, "To": number, "Body": text},
                    headers={"Authorization": f"Basic {auth}"},
                )
        logger.info("SMS sent for '%s'", name)
        return True
    except Exception as e:
        logger.error("SMS send failed: %s", e)
        return False


def _get_default_slack_webhook() -> str:
    from app.config import get_config
    return get_config().slack.default_webhook or ""


async def send_discord(webhook_url: str, name: str, summary: str) -> bool:
    import httpx
    try:
        embed = {
            "title": f"Nx-Citadel Report: {name}",
            "description": summary[:4000],
            "color": 0x5865F2,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"embeds": [embed]})
        ok = resp.status_code in (200, 204)
        logger.info("Discord send '%s': %s", name, "ok" if ok else resp.text)
        return ok
    except Exception as e:
        logger.error("Discord send failed: %s", e)
        return False


def _get_default_discord_webhook() -> str:
    from app.config import get_config
    return get_config().discord.default_webhook or ""


def list_reports(interest_id: str) -> list[dict]:
    report_dir = REPORTS_DIR / interest_id
    if not report_dir.exists():
        return []
    results = []
    for p in sorted(report_dir.glob("*.md"), reverse=True):
        results.append({
            "filename": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "modified": _ts_from_filename(p).isoformat(),
        })
    return results


async def read_report(interest_id: str, filename: str) -> str:
    path = REPORTS_DIR / interest_id / filename
    if not path.exists():
        return ""
    async with aiofiles.open(path) as f:
        return await f.read()


async def deliver_summary_outputs(summary_report: dict, content: str, output_sent: list[str]) -> None:
    output_cfg = summary_report.get("output", {})
    types = output_cfg.get("types", ["report"])

    path = await save_summary_report(summary_report["id"], summary_report["name"], content)
    output_sent.append(f"report:{path}")

    if "email" in types:
        recipients = output_cfg.get("email_recipients", [])
        if recipients:
            ok = await send_email(recipients, summary_report["name"], content)
            output_sent.append("email:ok" if ok else "email:failed")

    if "slack" in types:
        webhook = output_cfg.get("slack_webhook") or _get_default_slack_webhook()
        if webhook:
            ok = await send_slack(webhook, summary_report["name"], content)
            output_sent.append("slack:ok" if ok else "slack:failed")

    if "sms" in types:
        numbers = output_cfg.get("sms_numbers", [])
        if numbers:
            ok = await send_sms(numbers, summary_report["name"], content)
            output_sent.append("sms:ok" if ok else "sms:failed")

    if "discord" in types:
        webhook = output_cfg.get("discord_webhook") or _get_default_discord_webhook()
        if webhook:
            ok = await send_discord(webhook, summary_report["name"], content)
            output_sent.append("discord:ok" if ok else "discord:failed")


async def save_summary_report(report_id: str, name: str, content: str) -> str:
    now = datetime.now(timezone.utc)
    report_dir = SUMMARY_REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    path = report_dir / filename
    header = f"---\nreport_id: {report_id}\nname: {name}\ngenerated_at: {now.isoformat()}\n---\n\n"
    async with aiofiles.open(path, "w") as f:
        await f.write(header + content)
    logger.info("Summary report saved: %s", path)
    return str(path)


async def deliver_resource_outputs(resource: dict, summary: str, output_sent: list[str]) -> None:
    output_cfg = resource.get("output", {})
    types = output_cfg.get("types", [])

    path = await save_resource_report(resource["id"], resource["name"], summary)
    output_sent.append(f"report:{path}")

    if "email" in types:
        recipients = output_cfg.get("email_recipients", [])
        if recipients:
            ok = await send_email(recipients, resource["name"], summary)
            output_sent.append("email:ok" if ok else "email:failed")

    if "slack" in types:
        webhook = output_cfg.get("slack_webhook") or _get_default_slack_webhook()
        if webhook:
            ok = await send_slack(webhook, resource["name"], summary)
            output_sent.append("slack:ok" if ok else "slack:failed")

    if "sms" in types:
        numbers = output_cfg.get("sms_numbers", [])
        if numbers:
            ok = await send_sms(numbers, resource["name"], summary)
            output_sent.append("sms:ok" if ok else "sms:failed")

    if "discord" in types:
        webhook = output_cfg.get("discord_webhook") or _get_default_discord_webhook()
        if webhook:
            ok = await send_discord(webhook, resource["name"], summary)
            output_sent.append("discord:ok" if ok else "discord:failed")


async def save_resource_report(resource_id: str, name: str, content: str) -> str:
    now = datetime.now(timezone.utc)
    report_dir = RESOURCE_REPORTS_DIR / resource_id
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    path = report_dir / filename
    header = f"---\nresource_id: {resource_id}\nname: {name}\ngenerated_at: {now.isoformat()}\n---\n\n"
    async with aiofiles.open(path, "w") as f:
        await f.write(header + content)
    logger.info("Resource report saved: %s", path)
    return str(path)


def list_resource_reports(resource_id: str) -> list[dict]:
    report_dir = RESOURCE_REPORTS_DIR / resource_id
    if not report_dir.exists():
        return []
    results = []
    for p in sorted(report_dir.glob("*.md"), reverse=True):
        results.append({
            "filename": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "modified": _ts_from_filename(p).isoformat(),
        })
    return results


async def read_resource_report(resource_id: str, filename: str) -> str:
    path = RESOURCE_REPORTS_DIR / resource_id / filename
    if not path.exists():
        return ""
    async with aiofiles.open(path) as f:
        return await f.read()


def get_recent_resource_reports(max_age_days: int = 7, tags: set = None) -> list[dict]:
    """Return the most recent pre-collected report for each active resource within max_age_days.

    Only the single newest report per resource is returned. Frontmatter is stripped.
    If tags is provided, only resources sharing at least one tag are included.
    """
    from app.storage.markdown_store import resources_store
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    results = []

    for resource in resources_store.list():
        if not resource.get("active", True):
            continue

        if tags:
            res_tags = set(resource.get("tags", [])) | set(resource.get("topics", []))
            if not tags.intersection(res_tags):
                continue

        resource_id = resource["id"]
        resource_name = resource.get("name", resource_id)

        report_dir = RESOURCE_REPORTS_DIR / resource_id
        if not report_dir.exists():
            continue

        report_files = sorted(report_dir.glob("*.md"), reverse=True)
        if not report_files:
            continue

        latest = report_files[0]
        file_ts = _ts_from_filename(latest)
        if file_ts < cutoff:
            continue

        try:
            content = latest.read_text(encoding="utf-8")
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3:].lstrip("\n")
            results.append({
                "resource_id": resource_id,
                "resource_name": resource_name,
                "filename": latest.name,
                "ran_at": file_ts.isoformat(),
                "content": content[:4000],
            })
        except Exception as e:
            logger.warning("Failed to read resource report %s: %s", latest, e)

    return results


def list_summary_report_files(report_id: str) -> list[dict]:
    report_dir = SUMMARY_REPORTS_DIR / report_id
    if not report_dir.exists():
        return []
    results = []
    for p in sorted(report_dir.glob("*.md"), reverse=True):
        results.append({
            "filename": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "modified": _ts_from_filename(p).isoformat(),
        })
    return results


async def read_summary_report_file(report_id: str, filename: str) -> str:
    path = SUMMARY_REPORTS_DIR / report_id / filename
    if not path.exists():
        return ""
    async with aiofiles.open(path) as f:
        return await f.read()
