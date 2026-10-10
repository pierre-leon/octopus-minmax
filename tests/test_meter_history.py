import sys
import types
import unittest
from datetime import date, timedelta

sys.modules.setdefault("requests", types.ModuleType("requests"))

from account_manager import AccountManager
from meter_history import (
    half_hours_from_measurements,
    iter_chunks,
    measurement_variables,
    reading_from_measurement,
)
from query_service import gql_errors_are_permanent


def _node(start, value, unit="KILOWATT_HOURS", duration=1800):
    return {
        "value": value,
        "unit": unit,
        "startAt": start,
        "durationInSeconds": duration,
    }


def _page(nodes, has_next, cursor):
    return {"account": {"properties": [{"measurements": {
        "edges": [{"node": node} for node in nodes],
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
    }}]}}


class MeterHistoryTests(unittest.TestCase):
    def test_kilowatt_hours_become_watt_hours(self):
        reading, unknown = reading_from_measurement(
            _node("2025-12-02T00:30:00+00:00", "0.063")
        )
        self.assertIsNone(unknown)
        self.assertEqual(reading["readAt"], "2025-12-02T00:30:00Z")
        self.assertEqual(reading["consumptionDelta"], 63.0)

    def test_a_daily_total_is_left_out(self):
        reading, unknown = reading_from_measurement(
            _node("2025-12-02T00:00:00Z", "10", duration=86400)
        )
        self.assertIsNone(reading)
        self.assertIsNone(unknown)

    def test_unknown_unit_is_reported(self):
        page, unknown = half_hours_from_measurements(_page(
            [_node("2025-12-02T00:00:00Z", "1", unit="CUBIC_METRES")],
            False, None,
        )["account"])
        self.assertEqual(page, {})
        self.assertEqual(unknown, {"CUBIC_METRES"})

    def test_chunks_cover_every_day_once(self):
        start = date(2025, 10, 11)
        end = date(2026, 10, 10)
        seen = []
        for chunk_start, chunk_end in iter_chunks(start, end):
            self.assertLessEqual((chunk_end - chunk_start).days, 27)
            cursor = chunk_start
            while cursor <= chunk_end:
                seen.append(cursor)
                cursor += timedelta(days=1)
        self.assertEqual(seen[0], start)
        self.assertEqual(seen[-1], end)
        self.assertEqual(len(seen), len(set(seen)))

    def test_variables_match_the_usage_page(self):
        variables = measurement_variables(
            "A-1", "mpan", "device", date(2025, 12, 2), date(2025, 12, 31), "cursor-1",
        )
        filters = variables["utilityFilters"][0]["electricityFilters"]
        self.assertEqual(variables["first"], 300)
        self.assertEqual(variables["startAt"], "2025-12-02T00:00:00.000Z")
        self.assertEqual(variables["endAt"], "2025-12-31T23:59:59.999Z")
        self.assertEqual(variables["cursor"], "cursor-1")
        self.assertEqual(filters["readingFrequencyType"], "RAW_INTERVAL")
        self.assertEqual(filters["readingDirection"], "CONSUMPTION")
        self.assertEqual(filters["marketSupplyPointId"], "mpan")
        self.assertEqual(filters["deviceId"], "device")

    def test_thirty_day_telemetry_error_is_not_retried(self):
        errors = [{
            "message": "The start of the range is too far in the past.",
            "extensions": {"errorType": "VALIDATION", "errorCode": "KT-GB-4051"},
        }]
        self.assertTrue(gql_errors_are_permanent(errors))


class FakeQuery:
    def __init__(self):
        self.calls = []

    def execute_gql_query(self, query, variables=None, operation_name=None):
        self.calls.append((operation_name, variables, query))
        cursor = (variables or {}).get("cursor")
        if cursor:
            return _page([_node("2025-12-02T01:00:00Z", "0.4")], False, None)
        return _page([_node("2025-12-02T00:30:00+00:00", "0.2")], True, "page-2")


class FetchHistoryTests(unittest.TestCase):
    def test_a_year_is_paged_through_measurements(self):
        today = date.today()
        fake = FakeQuery()
        manager = AccountManager(fake, [])
        manager.mpan = "mpan"
        manager.device_id = "device"
        rows = {
            row["readAt"]: row["consumptionDelta"]
            for row in manager.fetch_consumption_between(today - timedelta(days=364), today)
        }

        self.assertEqual(rows["2025-12-02T00:30:00Z"], 200.0)
        self.assertEqual(rows["2025-12-02T01:00:00Z"], 400.0)
        self.assertTrue(all(name == "getMeasurements" for name, _, _ in fake.calls))
        self.assertTrue(all("smartMeterTelemetry" not in query for _, _, query in fake.calls))
        self.assertGreater(len(fake.calls), 2)
        self.assertTrue(any(variables.get("cursor") == "page-2" for _, variables, _ in fake.calls))
        oldest = min(variables["startAt"] for _, variables, _ in fake.calls)
        self.assertTrue(oldest.startswith((today - timedelta(days=364)).isoformat()))


if __name__ == "__main__":
    unittest.main()
