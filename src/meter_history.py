"""Half-hourly history from the website's measurements query.

The live telemetry feed rejects a start older than 30 days. The usage page
reads `measurements` instead, a month at a time. A week of half-hours
fits in one page.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple


CHUNK_DAYS = 28
PAGE_SIZE = 500
MAX_PAGES = 20
HALF_HOUR_SECONDS = 1800

_KWH_UNITS = {"KILOWATT_HOURS", "KILOWATT_HOUR", "KWH"}
_WH_UNITS = {"WATT_HOURS", "WATT_HOUR", "WH"}


def canonical_read_at(raw: str) -> str:
    """UTC half-hour stamp, so a London offset matches a Z telemetry stamp."""
    text = raw.strip().replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def measurement_timezone() -> str:
    return os.getenv("TZ", "Europe/London") or "Europe/London"


def watt_hours(value, unit) -> Optional[float]:
    if value is None or unit is None or value == "":
        return None
    name = str(unit).strip().upper()
    amount = float(value)
    if name in _KWH_UNITS:
        return amount * 1000.0
    if name in _WH_UNITS:
        return amount
    return None


def reading_from_measurement(node: dict) -> Tuple[Optional[dict], Optional[str]]:
    """One interval, in the telemetry shape (Wh). The second item is an unknown unit."""
    if not node:
        return None, None
    duration = node.get("durationInSeconds")
    if duration is not None and int(duration) != HALF_HOUR_SECONDS:
        return None, None
    start = node.get("startAt")
    if not start:
        return None, None
    wh = watt_hours(node.get("value"), node.get("unit"))
    if wh is None:
        unit = node.get("unit")
        return None, str(unit) if unit else None
    return {"readAt": canonical_read_at(start), "consumptionDelta": wh}, None


def half_hours_from_measurements(account: dict) -> Tuple[Dict[str, float], set]:
    found: Dict[str, float] = {}
    unknown = set()
    for prop in (account or {}).get("properties") or []:
        measurements = prop.get("measurements") or {}
        for edge in measurements.get("edges") or []:
            reading, unit = reading_from_measurement((edge or {}).get("node") or {})
            if reading:
                found[reading["readAt"]] = reading["consumptionDelta"]
            elif unit:
                unknown.add(unit)
    return found, unknown


def measurement_page_info(account: dict) -> dict:
    infos = []
    for prop in (account or {}).get("properties") or []:
        info = (prop.get("measurements") or {}).get("pageInfo")
        if info:
            infos.append(info)
    for info in infos:
        if info.get("hasNextPage"):
            return info
    return infos[0] if infos else {}


def measurement_variables(account_number: str, mpan: str, device_id: str, start: date, end: date,
                          cursor: Optional[str] = None, timezone: Optional[str] = None) -> dict:
    variables = {
        "accountNumber": account_number,
        "first": PAGE_SIZE,
        "startAt": f"{start.isoformat()}T00:00:00.000Z",
        "endAt": f"{end.isoformat()}T23:59:59.999Z",
        "timezone": timezone or measurement_timezone(),
        "utilityFilters": [{
            "electricityFilters": {
                "readingFrequencyType": "RAW_INTERVAL",
                "marketSupplyPointId": str(mpan),
                "readingDirection": "CONSUMPTION",
                "deviceId": device_id,
            }
        }],
    }
    if cursor:
        variables["cursor"] = cursor
    return variables


def iter_chunks(start: date, end: date, span_days: int = CHUNK_DAYS):
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=span_days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)
