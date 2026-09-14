"""Log in to octopus.energy with a real browser and capture the session cookie.

The login form is a Django form guarded by invisible hCaptcha, so a scripted
HTTP POST cannot complete it. A browser engine passes it silently, which is the
only reason Playwright is here - it logs in and hands back the `octosession`
cookie. Every other call the bot makes is plain HTTP.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger('octobot.browser_login')

LOGIN_URL = "https://octopus.energy/login/"
# Landing on any dashboard path means the credentials and captcha both passed.
POST_LOGIN_URL_FRAGMENT = "/dashboard"
SESSION_COOKIE_NAME = "octosession"


class BrowserLoginError(Exception):
    pass


def _cookie_expiry(raw_expires) -> Optional[datetime]:
    """Playwright reports expiry as a unix timestamp, or -1 for session cookies."""
    try:
        expires = float(raw_expires)
    except (TypeError, ValueError):
        return None
    if expires <= 0:
        return None
    return datetime.fromtimestamp(expires, tz=timezone.utc)


def fetch_web_session(email: str, password: str, timeout_ms: int = 120_000) -> Tuple[str, Optional[datetime]]:
    """Return (octosession cookie value, expiry) after a successful login."""
    if not email or not password:
        raise BrowserLoginError(
            "Octopus email and password are required to renew the website session. "
            "Set them in the add-on configuration."
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserLoginError(
            "Playwright is not installed in this image, so the website session cannot be renewed."
        ) from e

    logger.info("Logging in to octopus.energy to renew the website session")

    with sync_playwright() as playwright:
        # Chromium is the one with builds on both x64 and arm64, which the add-on needs.
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception:
            logger.warning("Chromium unavailable, falling back to Firefox")
            browser = playwright.firefox.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            page.goto(LOGIN_URL)
            page.get_by_placeholder("Email address").fill(email)
            page.get_by_placeholder("Password").fill(password)
            page.get_by_placeholder("Password").press("Enter")

            try:
                page.wait_for_url(f"**{POST_LOGIN_URL_FRAGMENT}**", timeout=timeout_ms)
            except Exception as e:
                raise BrowserLoginError(
                    f"Login did not reach the dashboard (still on {page.url}). "
                    "The password may be wrong, or Octopus may be asking for a captcha or 2FA."
                ) from e

            for entry in context.cookies():
                if entry.get("name") == SESSION_COOKIE_NAME and entry.get("value"):
                    expiry = _cookie_expiry(entry.get("expires"))
                    logger.info(
                        f"Captured {SESSION_COOKIE_NAME}; expires "
                        f"{expiry.isoformat() if expiry else 'unknown'}"
                    )
                    return entry["value"], expiry

            raise BrowserLoginError(
                f"Logged in but no {SESSION_COOKIE_NAME} cookie was set; the login flow may have changed."
            )
        finally:
            browser.close()
