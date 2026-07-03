import logging
from fastapi import APIRouter, Depends
from app.models import AppSettings
from app.config import get_config, save_config
from app.auth import require_manager
from app.services.logger_service import log_user_action

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def read_settings():
    cfg = get_config()
    data = cfg.model_dump()
    # Mask secrets in response
    if data["llm"]["api_key"]:
        data["llm"]["api_key"] = "***" + data["llm"]["api_key"][-4:]
    data["llm"]["api_keys"] = {
        provider: ("***" + key[-4:] if key else "")
        for provider, key in data["llm"]["api_keys"].items()
    }
    if data["email"]["smtp_password"]:
        data["email"]["smtp_password"] = "********"
    if data["sms"]["auth_token"]:
        data["sms"]["auth_token"] = "********"
    if data["search"]["brave_api_key"]:
        data["search"]["brave_api_key"] = "***" + data["search"]["brave_api_key"][-4:]
    if data["search"]["serpapi_key"]:
        data["search"]["serpapi_key"] = "***" + data["search"]["serpapi_key"][-4:]
    return data


@router.put("/")
def update_settings(new_settings: AppSettings, _u=Depends(require_manager)):
    current = get_config()
    data = new_settings.model_dump()

    # Resolve the incoming LLM key for the selected provider, preserving the stored
    # key if the client sent back the masked placeholder unchanged.
    provider = data["llm"]["provider"]
    incoming_key = data["llm"]["api_key"]
    stored_keys = dict(current.llm.api_keys)
    # Migrate a legacy single-key config (pre-api_keys-dict) into the dict.
    if current.llm.provider not in stored_keys and current.llm.api_key:
        stored_keys[current.llm.provider] = current.llm.api_key
    if incoming_key.startswith("***"):
        resolved_key = stored_keys.get(provider, "")
    else:
        resolved_key = incoming_key
    stored_keys[provider] = resolved_key
    data["llm"]["api_key"] = resolved_key
    data["llm"]["api_keys"] = stored_keys

    if data["email"]["smtp_password"] == "********":
        data["email"]["smtp_password"] = current.email.smtp_password
    if data["sms"]["auth_token"] == "********":
        data["sms"]["auth_token"] = current.sms.auth_token
    if data["search"]["brave_api_key"].startswith("***"):
        data["search"]["brave_api_key"] = current.search.brave_api_key
    if data["search"]["serpapi_key"].startswith("***"):
        data["search"]["serpapi_key"] = current.search.serpapi_key
    merged = AppSettings(**data)
    save_config(merged)
    log_user_action(logger, "Settings updated")
    return {"ok": True}


@router.post("/test-llm")
async def test_llm():
    from app.services.ai_service import test_connection
    cfg = get_config()
    result = await test_connection(cfg.llm.provider, cfg.llm.api_key, cfg.llm.model, cfg.llm.ollama_base_url)
    return result


@router.get("/ollama-models")
async def ollama_models(base_url: str = ""):
    from app.services.ai_service import list_ollama_models
    cfg = get_config()
    return await list_ollama_models(base_url or cfg.llm.ollama_base_url)


@router.post("/test-email")
async def test_email():
    cfg = get_config().email
    if not cfg.smtp_host or not cfg.from_address:
        return {"ok": False, "error": "Email not configured (smtp_host or from_address missing)"}
    try:
        import aiosmtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = cfg.from_address
        msg["To"] = cfg.from_address
        msg["Subject"] = "Nx-Citadel Email Test"
        msg.set_content("This is a test email from Nx-Citadel to verify SMTP configuration.")
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user or None,
            password=cfg.smtp_password or None,
            start_tls=cfg.use_tls,
        )
        log_user_action(logger, "Test email sent successfully to %s", cfg.from_address)
        return {"ok": True, "message": f"Test email sent to {cfg.from_address}"}
    except Exception as e:
        logger.error("Test email failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/test-sms")
async def test_sms(payload: dict):
    to_number = payload.get("to_number", "").strip()
    if not to_number:
        return {"ok": False, "error": "No test number provided"}
    cfg = get_config().sms
    if not cfg.account_sid or not cfg.auth_token or not cfg.from_number:
        return {"ok": False, "error": "SMS not configured (account_sid, auth_token, or from_number missing)"}
    try:
        import httpx, base64
        auth = base64.b64encode(f"{cfg.account_sid}:{cfg.auth_token}".encode()).decode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                data={"From": cfg.from_number, "To": to_number, "Body": "Nx-Citadel SMS test — configuration verified."},
                headers={"Authorization": f"Basic {auth}"},
            )
        if resp.status_code in (200, 201):
            log_user_action(logger, "Test SMS sent to %s", to_number)
            return {"ok": True, "message": f"Test SMS sent to {to_number}"}
        body = resp.json()
        return {"ok": False, "error": body.get("message", resp.text)}
    except Exception as e:
        logger.error("Test SMS failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/test-discord")
async def test_discord():
    webhook = get_config().discord.default_webhook
    if not webhook:
        return {"ok": False, "error": "Discord webhook not configured"}
    try:
        import httpx
        embed = {
            "title": "Nx-Citadel Discord Test",
            "description": "Discord webhook verified — Nx-Citadel is connected.",
            "color": 0x5865F2,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook, json={"embeds": [embed]})
        if resp.status_code in (200, 204):
            log_user_action(logger, "Test Discord message sent")
            return {"ok": True, "message": "Test message sent to Discord channel"}
        return {"ok": False, "error": f"Discord returned {resp.status_code}: {resp.text}"}
    except Exception as e:
        logger.error("Test Discord failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.get("/schedules")
def list_schedules():
    from app.services.scheduler_service import list_jobs
    return list_jobs()
