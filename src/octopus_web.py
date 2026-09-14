"""Client for the octopus.energy smart enrolment API.

This is the same API the Octopus website uses to move you between tariffs. It
replaced the `startOnboardingProcess` GraphQL mutation, which now refuses every
customer credential with KT-CT-1111.

Authentication is the website login session (`octosession`) plus a
`selectedAccount` cookie holding the account number. Tokens of any kind are
rejected here.

The API is journey-based rather than product-based: you ask for AGILE or COSY
and Octopus decides which product that currently sells. Because that product
may be a fixed-term one, callers must check the offered product code against
the one the comparison chose before enrolling.
"""

import json
import logging
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger('octobot.octopus_web')

BASE = "https://octopus.energy/smart/api"
ENROLMENT_DATA_URL = f"{BASE}/enrolment/enrolment-data/"
START_ENROLMENT_URL = f"{BASE}/enrolment/start-enrolment/"
SESSION_URL = f"{BASE}/auth/session/"

IMPORT_ELECTRICITY = "IMPORT_ELECTRICITY"

# Codes lifted from the site's own bundle, so failures read as something
# actionable instead of an opaque 500.
ERROR_MEANINGS = {
    "UKOB-AUTH-0200": "the website session is invalid or expired - a new browser login is needed",
    "UKOB-AUTH-0205": "Octopus rejected the request origin",
    "UKOB-AUTH-0412": "no account was selected",
    "OE-0101": "no authorization was provided",
    "OE-0102": "Octopus rejected the credential as the wrong kind",
    "OE-0103": "the account is not authorized for this action",
    "OE-0104": "the credential has expired",
    "UKST-ENRO-0310": "Octopus says this account is not eligible for that switch right now",
    "UKST-ENRO-0230": "Octopus could not return eligibility data for that journey/variant",
}

SESSION_EXPIRED_CODES = {"UKOB-AUTH-0200", "OE-0104"}


class OctopusWebError(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code

    @property
    def session_expired(self) -> bool:
        return self.code in SESSION_EXPIRED_CODES


def _extract_error(payload) -> Optional[str]:
    """Return an error code from either response shape Octopus uses."""
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return first.get("code") or first.get("name")
    if payload.get("code") and payload.get("data") is None:
        return payload.get("code")
    return None


class OctopusWebClient:
    def __init__(self, session_cookie: str, account_number: str, timeout: int = 60):
        if not session_cookie:
            raise OctopusWebError("No Octopus website session stored.", "UKOB-AUTH-0200")
        self.session_cookie = session_cookie
        self.account_number = account_number
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Cookie": f"octosession={self.session_cookie}; selectedAccount={self.account_number}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, body: Optional[dict] = None) -> dict:
        response = requests.request(
            method, url, headers=self._headers(), json=body, timeout=self.timeout
        )
        try:
            payload = response.json()
        except ValueError:
            raise OctopusWebError(
                f"Octopus returned a non-JSON response ({response.status_code}) from {url}"
            )

        code = _extract_error(payload)
        if code:
            meaning = ERROR_MEANINGS.get(code, "unrecognised error")
            raise OctopusWebError(f"Octopus enrolment API said {code}: {meaning}", code)
        if not response.ok:
            raise OctopusWebError(
                f"Octopus enrolment API failed ({response.status_code}): {json.dumps(payload)[:300]}"
            )
        return payload.get("data") if isinstance(payload.get("data"), dict) else payload

    def check_session(self) -> dict:
        """Cheap liveness check; reports isLoggedIn without touching enrolments."""
        return self._request("GET", SESSION_URL)

    def enrolment_data(self, journey: str, variant: Optional[str] = None) -> dict:
        params = {"journey": journey, "accountNumber": self.account_number}
        if variant:
            params["variant"] = variant
        return self._request("GET", f"{ENROLMENT_DATA_URL}?{urlencode(params)}")

    def start_enrolment(self, journey: str, property_id: int, mpan: str,
                        terms_accepted: bool = False) -> dict:
        body = {
            "journey": journey,
            "termsAndConditionsAccepted": terms_accepted,
            "propertyId": property_id,
            "candidates": [{
                "type": IMPORT_ELECTRICITY,
                "importMpan": mpan,
                "exportMpan": None,
                "gasMprn": None,
            }],
        }
        logger.debug(f"start-enrolment payload: {json.dumps(body)}")
        return self._request("POST", START_ENROLMENT_URL, body)


def offered_product_code(enrolment_data: dict) -> Optional[str]:
    """The product code Octopus would actually enrol you onto for this journey."""
    for tariff in enrolment_data.get("tariffs") or []:
        if tariff.get("type") == IMPORT_ELECTRICITY:
            return tariff.get("productCode")
    return None


def matching_candidate(enrolment_data: dict, mpan: str) -> Optional[dict]:
    for candidate in enrolment_data.get("candidates") or []:
        if candidate.get("importMpan") == mpan:
            return candidate
    return None


def ineligibility_reasons(enrolment_data: dict, candidate: Optional[dict] = None) -> list:
    reasons = []
    for key in ("accountIneligibilityMessages", "propertyIneligibilityMessages"):
        for message in enrolment_data.get(key) or []:
            reasons.append(str(message))
    if candidate:
        for message in candidate.get("ineligibilityMessages") or []:
            reasons.append(str(message))
    return reasons
