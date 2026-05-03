"""Authentication utilities, session management, and role-based access."""
import bcrypt
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request

COOKIE_NAME = "nx_session"
SESSION_TTL_HOURS = 12
MFA_PENDING_TTL_MINUTES = 5

ROLE_RANK = {"user": 1, "manager": 2, "admin": 3}

# In-memory session stores (survive only for the process lifetime — acceptable for a single-host app)
_sessions: dict[str, dict] = {}      # token -> session dict
_pending_mfa: dict[str, dict] = {}   # token -> {user_id, expires}


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user: dict) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "mfa_setup_required": user.get("mfa_setup_required", False),
        "expires": datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS),
    }
    return token

def get_session(token: str) -> dict | None:
    sess = _sessions.get(token)
    if not sess:
        return None
    if datetime.now(timezone.utc) > sess["expires"]:
        _sessions.pop(token, None)
        return None
    return sess

def delete_session(token: str) -> None:
    _sessions.pop(token, None)

def clear_all_sessions(except_token: str | None = None) -> int:
    """Invalidate every active session. Returns the number of sessions cleared."""
    tokens = [t for t in list(_sessions) if t != except_token]
    for t in tokens:
        _sessions.pop(t, None)
    return len(tokens)

def update_session(token: str, updates: dict) -> None:
    if token in _sessions:
        _sessions[token].update(updates)


# ── Pending MFA ───────────────────────────────────────────────────────────────

def create_pending_mfa(user_id: str) -> str:
    token = secrets.token_hex(16)
    _pending_mfa[token] = {
        "user_id": user_id,
        "expires": datetime.now(timezone.utc) + timedelta(minutes=MFA_PENDING_TTL_MINUTES),
    }
    return token

def consume_pending_mfa(token: str) -> str | None:
    pending = _pending_mfa.pop(token, None)
    if not pending:
        return None
    if datetime.now(timezone.utc) > pending["expires"]:
        return None
    return pending["user_id"]


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user

def require_manager(user: dict = Depends(get_current_user)) -> dict:
    if ROLE_RANK.get(user["role"], 0) < ROLE_RANK["manager"]:
        raise HTTPException(403, "Manager or Admin role required")
    return user

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        raise HTTPException(403, "Admin role required")
    return user
