import sys
import types
import unittest
from datetime import datetime, timedelta

sys.modules.setdefault("requests", types.ModuleType("requests"))

from comparison_engine import cosy_series, covered_rows, rate_value_at


def _half_hours(start):
    moment = datetime.fromisoformat(start.replace("Z", "+00:00"))
    rows = []
    for _ in range(48):
        rows.append({"readAt": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "consumptionDelta": 100})
        moment += timedelta(minutes=30)
    return rows


def _agile_until(last_start):
    """Half-hours from 00:00Z through last_start, each half an hour long."""
    moment = datetime.fromisoformat("2026-10-11T00:00:00+00:00")
    end = datetime.fromisoformat(last_start.replace("Z", "+00:00"))
    rates = []
    while moment <= end:
        nxt = moment + timedelta(minutes=30)
        rates.append({
            "valid_from": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valid_to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value_inc_vat": 20.0,
            "payment_method": None,
        })
        moment = nxt
    return rates


def _cosy_day():
    """Bands through local midnight, which is 23:00Z during BST."""
    edges = [
        "2026-10-10T23:00:00Z",
        "2026-10-11T03:00:00Z",
        "2026-10-11T13:00:00Z",
        "2026-10-11T16:00:00Z",
        "2026-10-11T18:00:00Z",
        "2026-10-11T21:00:00Z",
        "2026-10-11T23:00:00Z",
    ]
    return [
        {
            "valid_from": start,
            "valid_to": end,
            "value_inc_vat": 15.0,
            "payment_method": None,
        }
        for start, end in zip(edges, edges[1:])
    ]


class CoveredRowsTests(unittest.TestCase):
    def test_unpublished_agile_tail_is_left_out_of_both(self):
        # 21:30Z is 22:30 BST, the last half-hour that was published.
        profile = _half_hours("2026-10-11T00:00:00Z")
        kept, skipped = covered_rows(profile, [_agile_until("2026-10-11T21:30:00Z"), _cosy_day()])
        self.assertEqual(skipped, 4)
        self.assertEqual(kept[-1][0]["readAt"], "2026-10-11T21:30:00Z")
        self.assertEqual(len(kept), 44)

    def test_a_stamp_on_the_boundary_belongs_to_the_later_rate(self):
        profile = [{"readAt": "2026-10-11T22:00:00Z", "consumptionDelta": 100}]
        agile = _agile_until("2026-10-11T21:30:00Z")
        kept, skipped = covered_rows(profile, [agile, _cosy_day()])
        self.assertEqual(skipped, 1)
        self.assertEqual(kept, [])

    def test_a_missing_cosy_slot_uses_yesterday(self):
        today = [{
            "valid_from": "2026-10-22T00:00:00Z",
            "valid_to": "2026-10-22T12:00:00Z",
            "value_inc_vat": 20.0,
            "payment_method": None,
        }]
        yesterday = [{
            "valid_from": "2026-10-21T12:00:00Z",
            "valid_to": "2026-10-21T23:00:00Z",
            "value_inc_vat": 12.5,
            "payment_method": None,
        }]
        stamps = ["2026-10-22T01:00:00Z", "2026-10-22T18:00:00Z", "2026-10-22T23:30:00Z"]
        series = cosy_series(today, yesterday, stamps)
        self.assertEqual(series, [20.0, 12.5, None])
        self.assertIsNone(rate_value_at(today, stamps[1]))


if __name__ == "__main__":
    unittest.main()
