"""Yesterday's forecast, so tonight can say how far out it was."""

import json
import os
from datetime import date, timedelta
from typing import Optional


def recalled_kwh(path: str, day: date) -> Optional[float]:
    value = _read(path).get(day.isoformat())
    if value is None:
        return None
    return float(value)


def remember_kwh(path: str, day: date, kwh: float) -> None:
    stored = _read(path)
    stored[day.isoformat()] = round(float(kwh), 4)
    cutoff = (day - timedelta(days=21)).isoformat()
    kept = {stamp: value for stamp, value in stored.items() if stamp >= cutoff}
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(kept, handle)


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
