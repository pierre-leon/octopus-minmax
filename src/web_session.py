"""Storage for the octopus.energy website session cookie.

The enrolment endpoints behind /smart/api/ accept only a browser login session
(the `octosession` cookie). That session cannot be minted from an API key, a
Kraken token or any OAuth client, so the bot logs in with a real browser and
keeps the cookie here until it nears expiry.

Octopus issues it with a fixed 7-day lifetime and does not extend it on use, so
the bot renews it ahead of time rather than waiting for a switch to fail.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger('octobot.web_session')

_lock = threading.Lock()


def web_session_path() -> str:
    override = os.getenv("WEB_SESSION_PATH", "").strip()
    if override:
        return override
    if os.path.isdir("/data"):
        return "/data/octopus_web_session.json"
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", "octopus_web_session.json")


def credentials_path() -> str:
    return web_session_path().replace("octopus_web_session.json", "octopus_web_credentials.json")


def save_credentials(email: str, password: str) -> None:
    """Persist the login so renewals need no further interaction.

    Renewal is a real browser login, so the password has to be stored
    somewhere. It lives beside the session, readable only by the bot.
    """
    path = credentials_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp"
    with _lock:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"email": email, "password": password}, f)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    logger.info("Saved Octopus website credentials for automatic session renewal")


def clear_credentials() -> None:
    path = credentials_path()
    with _lock:
        if os.path.isfile(path):
            os.remove(path)


def credentials() -> tuple:
    """(email, password) from the add-on configuration, else the dashboard login."""
    import config
    if config.OCTOPUS_EMAIL and config.OCTOPUS_PASSWORD:
        return config.OCTOPUS_EMAIL, config.OCTOPUS_PASSWORD
    path = credentials_path()
    if not os.path.isfile(path):
        return "", ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("email") or "", data.get("password") or ""
    except Exception as e:
        logger.warning(f"Failed to read stored credentials: {e}")
        return "", ""


def has_credentials() -> bool:
    email, password = credentials()
    return bool(email and password)


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
