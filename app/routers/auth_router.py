import base64
import io
import logging
import pyotp
import qrcode
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import (
    COOKIE_NAME, SESSION_TTL_HOURS,
    create_pending_mfa, consume_pending_mfa,
    create_session, delete_session, get_session, update_session,
    hash_password, verify_password,
)
from app.storage.user_store import users_store
from app.services.logger_service import log_user_action

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ── Login page ────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token and get_session(token):
        return RedirectResponse("/", 302)
    return templates.TemplateResponse("login.html", {"request": request})


# ── Auth API ──────────────────────────────────────────────────────────────────

@router.post("/api/auth/login")
async def login(request: Request, response: Response):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = users_store.get_by_username(username)
    if not user or not verify_password(password, user.get("password_hash", "")):
        logger.warning("Failed login attempt for username: %s", username)
        raise HTTPException(401, "Invalid username or password")

    role = user.get("role", "user")
    mfa_enabled = user.get("mfa_enabled", False)
    mfa_exempt = user.get("mfa_exempt", False)
    mfa_required_for_role = role in ("manager", "admin")

    # Manager/admin without MFA set up: allow in but flag for setup
    mfa_setup_required = mfa_required_for_role and not mfa_enabled and not mfa_exempt

    # MFA challenge needed: user has MFA enabled
    if mfa_enabled:
        pending_token = create_pending_mfa(user["id"])
        log_user_action(logger, "MFA challenge issued for: %s", username)
        return {"ok": True, "requires_mfa": True, "pending_token": pending_token}

    # No MFA — create full session
    if mfa_setup_required:
        user = {**user, "mfa_setup_required": True}
    token = create_session(user)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True, samesite="lax",
    )
    log_user_action(logger, "Login: %s (%s)", username, role)
    return {"ok": True, "requires_mfa": False, "mfa_setup_required": mfa_setup_required}


@router.post("/api/auth/verify-mfa")
async def verify_mfa(request: Request, response: Response):
    data = await request.json()
    pending_token = data.get("pending_token", "")
    code = data.get("code", "").replace(" ", "")

    user_id = consume_pending_mfa(pending_token)
    if not user_id:
        raise HTTPException(401, "MFA session expired — please log in again")

    user = users_store.get(user_id)
    if not user:
        raise HTTPException(401, "User not found")

    secret = user.get("mfa_secret", "")
    if not secret:
        raise HTTPException(400, "MFA not configured for this account")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        logger.warning("Failed MFA code for user: %s", user.get("username"))
        raise HTTPException(401, "Invalid authentication code")

    token = create_session(user)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True, samesite="lax",
    )
    log_user_action(logger, "MFA verified, login complete: %s", user.get("username"))
    return {"ok": True}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        sess = get_session(token)
        if sess:
            log_user_action(logger, "Logout: %s", sess.get("username"))
        delete_session(token)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(401, "Not authenticated")
    user = users_store.get(sess["user_id"])
    if not user:
        raise HTTPException(401, "User not found")
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "mfa_enabled": user.get("mfa_enabled", False),
        "mfa_exempt": user.get("mfa_exempt", False),
        "mfa_setup_required": sess.get("mfa_setup_required", False),
    }


@router.get("/api/auth/setup-mfa")
def setup_mfa_begin(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(401, "Not authenticated")

    user = users_store.get(sess["user_id"])
    if not user:
        raise HTTPException(404, "User not found")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user["username"], issuer_name="Nx-Citadel")

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Store pending secret until confirmed
    users_store.update(sess["user_id"], {"mfa_secret_pending": secret})
    return {"qr_code": qr_b64, "secret": secret}


@router.post("/api/auth/confirm-mfa")
async def confirm_mfa(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(401, "Not authenticated")

    data = await request.json()
    code = data.get("code", "").replace(" ", "")

    user = users_store.get(sess["user_id"])
    if not user:
        raise HTTPException(404, "User not found")

    pending_secret = user.get("mfa_secret_pending", "")
    if not pending_secret:
        raise HTTPException(400, "No pending MFA setup — start setup again")

    totp = pyotp.TOTP(pending_secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Incorrect code — try again")

    users_store.update(sess["user_id"], {
        "mfa_secret": pending_secret,
        "mfa_secret_pending": "",
        "mfa_enabled": True,
        "mfa_exempt": False,
    })
    # Clear mfa_setup_required from the current session
    update_session(token, {"mfa_setup_required": False})
    log_user_action(logger, "MFA enabled for user: %s", user.get("username"))
    return {"ok": True, "message": "MFA enabled successfully"}


@router.post("/api/auth/disable-mfa")
async def disable_mfa(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(401, "Not authenticated")

    data = await request.json()
    code = data.get("code", "").replace(" ", "")

    user = users_store.get(sess["user_id"])
    if not user:
        raise HTTPException(404, "User not found")

    secret = user.get("mfa_secret", "")
    if not secret:
        raise HTTPException(400, "MFA is not enabled")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Incorrect code — MFA not disabled")

    users_store.update(sess["user_id"], {
        "mfa_secret": "",
        "mfa_enabled": False,
    })
    log_user_action(logger, "MFA disabled for user: %s", user.get("username"))
    return {"ok": True, "message": "MFA disabled"}


@router.post("/api/auth/change-password")
async def change_password(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(401, "Not authenticated")

    data = await request.json()
    current_pw = data.get("current_password", "")
    new_pw = data.get("new_password", "")

    if len(new_pw) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    user = users_store.get(sess["user_id"])
    if not user:
        raise HTTPException(404, "User not found")

    if not verify_password(current_pw, user.get("password_hash", "")):
        raise HTTPException(400, "Current password is incorrect")

    users_store.update(sess["user_id"], {"password_hash": hash_password(new_pw)})
    log_user_action(logger, "Password changed for user: %s", user.get("username"))
    return {"ok": True, "message": "Password changed successfully"}
