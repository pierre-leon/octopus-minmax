"""Decide the Agile/Cosy hop for one evening.

Cosy, accepted today, starts this morning. Agile starts at the next midnight.
Joining Agile is a prediction, so it uses a higher bar. Leaving Agile for Cosy
uses the day already metered, and can wait until that day is over.
"""

from collections import defaultdict
from datetime import date, datetime
from typing import Optional, Sequence


PREDICTION_DAYS = 7


def decide_hop(current_id: str, today_cosy_cheaper: bool, tomorrow_agile_cheaper: bool) -> list:
    """Tariff ids to enrol, in order.

    The two flags are already compared with their own thresholds.
    """
    if current_id == "agile":
        if not today_cosy_cheaper:
            return []
        if tomorrow_agile_cheaper:
            return ["cosy", "agile"]
        return ["cosy"]
    if current_id == "cosy":
        if tomorrow_agile_cheaper:
            return ["agile"]
        return []
    return []


def saving_pence(dearer: Optional[float], cheaper: Optional[float]) -> Optional[float]:
    """How much dearer exceeds cheaper. Positive means cheaper really is cheaper."""
    if dearer is None or cheaper is None:
        return None
    return dearer - cheaper


def predicted_consumption(history: Sequence[dict], day: date) -> list:
    """A full day of half-hours on `day`, averaged from earlier days.

    Slots are matched on UTC clock time, which is how the rates are stamped.
    """
    buckets = defaultdict(list)
    for entry in history:
        raw = entry.get("readAt")
        if not raw:
            continue
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        clock = moment.strftime("%H:%M:%S")
        buckets[clock].append(float(entry.get("consumptionDelta") or 0))

    predicted = []
    for clock in sorted(buckets):
        values = buckets[clock]
        predicted.append({
            "readAt": f"{day.isoformat()}T{clock}Z",
            "consumptionDelta": sum(values) / len(values),
        })
    return predicted


def history_day_count(history: Sequence[dict]) -> int:
    days = set()
    for entry in history:
        raw = entry.get("readAt")
        if not raw:
            continue
        days.add(datetime.fromisoformat(raw.replace("Z", "+00:00")).date())
    return len(days)
