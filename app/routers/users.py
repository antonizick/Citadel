import logging
from fastapi import APIRouter, Depends, HTTPException
from app.auth import hash_password, require_admin
from app.storage.user_store import users_store
from app.services.logger_service import log_user_action

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe(user: dict) -> dict:
    """Strip secrets from user record before returning to client."""
    return {k: v for k, v in user.items()
            if k not in ("password_hash", "mfa_secret", "mfa_secret_pending", "_body")}


@router.get("/")
def list_users(_user=Depends(require_admin)):
    return [_safe(u) for u in users_store.list()]


@router.post("/", status_code=201)
async def create_user(payload: dict, _user=Depends(require_admin)):
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    role = payload.get("role", "user")

    if not username:
        raise HTTPException(400, "Username is required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if role not in ("user", "manager", "admin"):
        raise HTTPException(400, "Invalid role")
    if users_store.username_exists(username):
        raise HTTPException(409, f"Username '{username}' is already taken")

    user = users_store.create({
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "mfa_enabled": False,
        "mfa_secret": "",
        "mfa_exempt": False,
    })
    log_user_action(logger, "Created user: %s (%s)", username, role)
    return _safe(user)


@router.put("/{user_id}")
async def update_user(user_id: str, payload: dict, current_user=Depends(require_admin)):
    if user_id == current_user["user_id"] and "role" in payload:
        # Prevent admin from demoting themselves
        if payload["role"] != "admin":
            raise HTTPException(400, "You cannot change your own role")

    existing = users_store.get(user_id)
    if not existing:
        raise HTTPException(404, "User not found")

    updates: dict = {}
    if "role" in payload and payload["role"] in ("user", "manager", "admin"):
        updates["role"] = payload["role"]
    if "mfa_exempt" in payload:
        updates["mfa_exempt"] = bool(payload["mfa_exempt"])
    if "password" in payload and payload["password"]:
        if len(payload["password"]) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        updates["password_hash"] = hash_password(payload["password"])

    updated = users_store.update(user_id, updates)
    log_user_action(logger, "Updated user: %s", existing.get("username"))
    return _safe(updated)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, current_user=Depends(require_admin)):
    if user_id == current_user["user_id"]:
        raise HTTPException(400, "You cannot delete your own account")
    if not users_store.delete(user_id):
        raise HTTPException(404, "User not found")
    log_user_action(logger, "Deleted user ID: %s", user_id)


@router.post("/{user_id}/reset-mfa")
def reset_user_mfa(user_id: str, _user=Depends(require_admin)):
    user = users_store.get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    users_store.update(user_id, {
        "mfa_enabled": False,
        "mfa_secret": "",
        "mfa_secret_pending": "",
        "mfa_exempt": True,
    })
    log_user_action(logger, "MFA reset for user: %s", user.get("username"))
    return {"ok": True, "message": f"MFA reset for {user.get('username')} — they can now set up MFA again"}
