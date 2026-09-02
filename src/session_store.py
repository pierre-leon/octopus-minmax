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


def public_status() -> dict:
    session = load()
    if not session:
        return {
            "connected": False,
            "can_switch": False,
            "email": None,
            "grant_type": None,
            "refresh_expires_at": None,
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
        "refresh_expires_at": expires_at,
    }


def session_from_token_response(data: dict, can_switch: bool) -> dict:
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "refresh_token": data.get("refreshToken"),
        "refresh_expires_in": data.get("refreshExpiresIn"),
        "email": payload.get("email"),
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
