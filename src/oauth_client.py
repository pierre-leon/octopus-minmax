import base64
import hashlib
import json
import logging
import secrets
import time
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

logger = logging.getLogger("octobot.oauth_client")

# Public GraphiQL client from https://api.octopus.energy/v1/graphql/
# Redirect is fixed to that IDE; the bot starts PKCE and you paste the code or refresh token back.
DEFAULT_OAUTH_CLIENT_ID = "534ca698825976bcf22c3e7e40fa6c5b435feb19d3748274c5b4a017d5888e0a"
AUTH_AUTHORIZE_URL = "https://auth.octopus.energy/authorize/"
AUTH_TOKEN_URL = "https://auth.octopus.energy/token/"
OAUTH_REDIRECT_URI = "https://api.octopus.energy/v1/graphql/"
DEFAULT_SCOPES = "full-customer-access"


def client_id() -> str:
    import config
    return (getattr(config, "OAUTH_CLIENT_ID", "") or DEFAULT_OAUTH_CLIENT_ID).strip()


def decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


def unix_expiry_from_oauth_response(data: dict) -> Optional[int]:
    """Return a unix timestamp if Octopus reported refresh lifetime; else None."""
    now = int(time.time())
    for key in ("refresh_expires_in", "refresh_token_expires_in", "refresh_expires_at"):
        val = data.get(key)
        if val is None:
            continue
        try:
            val = int(val)
        except (TypeError, ValueError):
            continue
        if val > 10 ** 9:
            return val
        if val > 0:
            return now + val
    return None


def expiry_fields_for_log(data: dict) -> dict:
    skip = {"access_token", "refresh_token", "id_token"}
    out = {}
    for key, value in data.items():
        if key in skip:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
    return out


def create_pkce_flow(scopes: str = DEFAULT_SCOPES) -> dict:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client_id(),
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": scopes,
    }
    return {
        "code_verifier": verifier,
        "state": state,
        "scope": scopes,
        "authorize_url": f"{AUTH_AUTHORIZE_URL}?{urlencode(params)}",
        "created_at": int(time.time()),
    }


def _post_token(form: dict) -> dict:
    response = requests.post(
        AUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=form,
        timeout=60,
    )
    try:
        data = response.json()
    except ValueError as e:
        raise Exception(f"OAuth token request returned non-JSON ({response.status_code})") from e
    if not response.ok or data.get("error"):
        description = data.get("error_description") or data.get("error") or response.text[:200]
        raise Exception(f"OAuth token request failed: {description}")
    if not data.get("access_token"):
        raise Exception("OAuth token request did not return an access_token")
    logger.info(f"OAuth token ok; fields={expiry_fields_for_log(data)}")
    return data


def exchange_authorization_code(code: str, code_verifier: str) -> dict:
    return _post_token({
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": OAUTH_REDIRECT_URI,
        "client_id": client_id(),
        "code_verifier": code_verifier,
    })


def refresh_access_token(refresh_token: str, oauth_client_id: Optional[str] = None) -> dict:
    return _post_token({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": oauth_client_id or client_id(),
    })


def parse_oauth_paste(raw: str) -> dict:
    """Accept an authorize redirect URL, an authorization code, or a refresh token."""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise Exception("Paste the authorization code, the GraphQL redirect URL, or the refresh token.")

    if text.startswith("eyJ"):
        raise Exception("That looks like an access token (expires in 1 hour). Paste the refresh_token or the URL code= value instead.")

    if "://" in text or text.lower().startswith("code="):
        parsed = urlparse(text if "://" in text else f"https://api.octopus.energy/v1/graphql/?{text}")
        query = parse_qs(parsed.query)
        if query.get("error"):
            raise Exception(query.get("error_description", query["error"])[0])
        code = (query.get("code") or [None])[0]
        if not code:
            raise Exception("Could not find code= in that URL.")
        return {"kind": "code", "value": code}

    compact = "".join(text.split())
    if all(c in "0123456789abcdefABCDEF" for c in compact) and len(compact) >= 32:
        return {"kind": "refresh", "value": compact}

    return {"kind": "code", "value": compact}
