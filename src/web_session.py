"""Storage for the octopus.energy website session cookie.

The enrolment endpoints behind /smart/api/ accept only a browser login session
(the `octosession` cookie). Nothing the bot can mint substitutes for it: API
keys, password grants, OAuth tokens and pre-signed scoped tokens are all
refused, and Octopus guards the login form with a captcha that challenges any
automated browser. So the cookie is copied in by hand and kept here.

Octopus issues it with a fixed 7-day lifetime and does not extend it on use, so
the bot warns ahead of expiry rather than waiting for a switch to fail.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger('octobot.web_session')

_lock = threading.Lock()

# Octopus sets the cookie with Max-Age=604800 and never extends it.
LIFETIME_DAYS = 7


def assumed_expiry() -> datetime:
    """A pasted cookie carries no expiry, so date it from now.

    It is normally copied out of a browser within minutes of logging in. If it
    was older than that the bot simply finds out sooner that the session has
    stopped working, and asks for another.
    """
    return datetime.now(timezone.utc) + timedelta(days=LIFETIME_DAYS)


def web_session_path() -> str:
    override = os.getenv("WEB_SESSION_PATH", "").strip()
    if override:
        return override
    if os.path.isdir("/data"):
        return "/data/octopus_web_session.json"
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", "octopus_web_session.json")


def load() -> Optional[dict]:
    path = web_session_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("cookie"):
            return None
        return data
    except Exception as e:
        logger.warning(f"Failed to read web session file: {e}")
        return None


def save(cookie: str, expires_at: Optional[datetime] = None, email: Optional[str] = None) -> dict:
    session = {
        "cookie": cookie,
        "expires_at": expires_at.astimezone(timezone.utc).isoformat() if expires_at else None,
        "email": email,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = web_session_path()
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
    logger.info(f"Saved Octopus web session to {path} (expires {session['expires_at'] or 'unknown'})")
    return session


def clear() -> None:
    path = web_session_path()
    with _lock:
        if os.path.isfile(path):
            os.remove(path)
            logger.info("Cleared Octopus web session")


def expires_at(session: Optional[dict] = None) -> Optional[datetime]:
    session = session if session is not None else load()
    if not session:
        return None
    raw = session.get("expires_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def cookie(session: Optional[dict] = None) -> Optional[str]:
    session = session if session is not None else load()
    return (session or {}).get("cookie")


def is_expired(session: Optional[dict] = None) -> bool:
    """Only reports True when we know the expiry and it has passed."""
    expiry = expires_at(session)
    if expiry is None:
        return False
    return datetime.now(timezone.utc) >= expiry


def is_usable(session: Optional[dict] = None) -> bool:
    session = session if session is not None else load()
    return bool(cookie(session)) and not is_expired(session)


def needs_renewal(lead_days: int, session: Optional[dict] = None) -> bool:
    """True when there's no session, or it expires within the lead window.

    An unknown expiry counts as due, so a session of unknown age is refreshed
    rather than trusted.
    """
    session = session if session is not None else load()
    if not cookie(session):
        return True
    expiry = expires_at(session)
    if expiry is None:
        return True
    return datetime.now(timezone.utc) + timedelta(days=lead_days) >= expiry


def remaining_days(session: Optional[dict] = None) -> Optional[float]:
    expiry = expires_at(session)
    if expiry is None:
        return None
    return (expiry - datetime.now(timezone.utc)).total_seconds() / 86400


def public_status() -> dict:
    session = load()
    if not session:
        return {
            "connected": False,
            "email": None,
            "expires_at": None,
            "expiry_known": False,
            "remaining_days": None,
            "expired": False,
        }
    expiry = expires_at(session)
    return {
        "connected": True,
        "email": session.get("email"),
        "expires_at": expiry.strftime("%Y-%m-%d %H:%M UTC") if expiry else None,
        "expiry_known": expiry is not None,
        "remaining_days": remaining_days(session),
        "expired": is_expired(session),
    }
