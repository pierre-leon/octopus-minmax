import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import logging

logger = logging.getLogger('octobot.session_store')

_lock = threading.Lock()

CUSTOMER_GRANT_TYPES = {
    "EMAIL-AND-PASSWORD",
    "AUTHORIZATION-CODE",
    "REFRESH-TOKEN",
    "OAUTH",
}


def session_path() -> str:
    override = os.getenv("SESSION_PATH", "").strip()
    if override:
        return override
    if os.path.isdir("/data"):
        return "/data/octopus_session.json"
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", "octopus_session.json")


def pending_oauth_path() -> str:
    return session_path().replace("octopus_session.json", "octopus_oauth_pending.json")


def load_pending_oauth() -> Optional[dict]:
    path = pending_oauth_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        created = int(data.get("created_at") or 0)
        if created and (datetime.now(timezone.utc).timestamp() - created) > 20 * 60:
            clear_pending_oauth()
            return None
        return data
    except Exception as e:
        logger.warning(f"Failed to read pending OAuth file: {e}")
        return None


def save_pending_oauth(pending: dict) -> None:
    path = pending_oauth_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp"
    with _lock:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def clear_pending_oauth() -> None:
    path = pending_oauth_path()
    with _lock:
        if os.path.isfile(path):
            os.remove(path)


def load() -> Optional[dict]:
    path = session_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("refresh_token"):
            return None
        return data
    except Exception as e:
        logger.warning(f"Failed to read session file: {e}")
        return None


def save(session: dict) -> None:
    path = session_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp"
    with _lock:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    logger.info(f"Saved Octopus session to {path}")


def clear() -> None:
    path = session_path()
    with _lock:
        if os.path.isfile(path):
            os.remove(path)
            logger.info("Cleared Octopus session")


def can_switch() -> bool:
    session = load()
    return bool(session and session.get("can_switch"))


def is_oauth_session(session: Optional[dict] = None) -> bool:
    if session is None:
        session = load()
    return bool(session and session.get("auth_kind") == "oauth")


def oauth_keepalive_due(max_age_seconds: int = 6 * 3600) -> bool:
    session = load()
    if not is_oauth_session(session):
        return False
    updated = session.get("updated_at")
    if not updated:
        return True
    try:
        last = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return True
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return age >= max_age_seconds


def public_status() -> dict:
    session = load()
    if not session:
        return {
            "connected": False,
            "can_switch": False,
            "email": None,
            "grant_type": None,
            "scope": None,
            "auth_kind": None,
            "refresh_expires_at": None,
            "refresh_expiry_known": False,
        }
    expires = session.get("refresh_expires_in")
    expires_at = None
    if isinstance(expires, int) and expires > 0:
        expires_at = datetime.fromtimestamp(expires, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "connected": True,
        "can_switch": bool(session.get("can_switch")),
        "email": session.get("email"),
        "grant_type": session.get("grant_type"),
        "scope": session.get("scope"),
        "auth_kind": session.get("auth_kind"),
        "refresh_expires_at": expires_at,
        "refresh_expiry_known": bool(expires_at),
    }


def session_from_oauth_response(data: dict, previous: Optional[dict] = None) -> dict:
    from oauth_client import decode_jwt_payload, unix_expiry_from_oauth_response

    previous = previous or {}
    payload = decode_jwt_payload(data.get("access_token") or "")
    email = payload.get("email") or previous.get("email")
    refresh_token = data.get("refresh_token") or previous.get("refresh_token")
    expires = unix_expiry_from_oauth_response(data)
    if expires is None:
        expires = previous.get("refresh_expires_in")
    return {
        "auth_kind": "oauth",
        "refresh_token": refresh_token,
        "refresh_expires_in": expires,
        "email": email,
        "grant_type": payload.get("gty") or "AUTHORIZATION-CODE",
        "scope": data.get("scope") or previous.get("scope") or payload.get("scope"),
        "can_switch": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def session_from_token_response(data: dict, can_switch: bool) -> dict:
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "refresh_token": data.get("refreshToken"),
        "refresh_expires_in": data.get("refreshExpiresIn"),
        "email": payload.get("email"),
        "auth_kind": "kraken",
        "grant_type": payload.get("gty"),
        "can_switch": can_switch,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def grant_type_allows_switch(grant_type: Optional[str]) -> bool:
    if not grant_type:
        return False
    normalised = grant_type.upper().replace("_", "-")
    if normalised in CUSTOMER_GRANT_TYPES:
        return True
    if "API" in normalised and "KEY" in normalised:
        return False
    return normalised in {"EMAIL-AND-PASSWORD", "AUTHORIZATION-CODE"}
