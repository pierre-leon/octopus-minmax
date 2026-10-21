import sys
import types
import unittest
from datetime import date

sys.modules.setdefault("requests", types.ModuleType("requests"))

from comparison_engine import ComparisonResult, CostBreakdown, TariffComparison
from report import (
    early_report_needed,
    format_report,
    hop_decision_line,
    with_version,
)
from tariff import Tariff


def _tariff(tariff_id, name):
    return Tariff(tariff_id, name, name, tariff_id, tariff_id, True)


def _priced(tariff_id, name, total_pence, unit_pence, kwh, standing=0):
    return TariffComparison(
        tariff=_tariff(tariff_id, name),
        cost_breakdown=CostBreakdown(
            consumption_cost=unit_pence * kwh,
            standing_charge=standing,
            total_cost=total_pence,
            total_kwh=kwh,
        ),
    )


class ReportTests(unittest.TestCase):
    def _result(self):
        kwh = 7.10
        current = _priced("cosy", "Cosy Octopus", 223, 23.1, kwh, standing=50)
        alternatives = [
            _priced("go", "Octopus Go", 240, 24.2, kwh, standing=52),
            _priced("agile", "Agile Octopus", 327, 27.4, kwh, standing=53),
            _priced("flexible", "Flexible Octopus", 242, 24.3, kwh, standing=51),
        ]
        return ComparisonResult(current, alternatives, current.tariff, 0)

    def _prediction(self):
        kwh = 6.82
        profile = [{"readAt": "2026-10-22T00:00:00Z", "consumptionDelta": kwh * 1000}]
        return {
            "method": "ensemble",
            "detail": "",
            "profile": profile,
            "agile": _priced("agile", "Agile Octopus", 340, 27.9, kwh, standing=52),
            "cosy": _priced("cosy", "Cosy Octopus", 270, 23.9, kwh, standing=54),
        }

    def test_the_report_bolds_the_cheapest_and_puts_standing_charge_on_tomorrow(self):
        text = format_report(
            self._result(),
            self._prediction(),
            None,
            "Staying on Cosy.",
        )
        self.assertEqual(text, "\n".join([
            "*Today 7.10 kWh*",
            "*Cosy £2.23* | 23.1p",
            "Go £2.40 | 24.2p",
            "Agile £3.27 | 27.4p",
            "Flex £2.42 | 24.3p",
            "",
            "*Tomorrow 6.82kWh*",
            "Agile £3.40 | 27.9p | sc 52p",
            "*Cosy £2.70* | 23.9p | sc 54p",
            "Staying on Cosy.",
        ]))

    def test_version_is_only_on_the_first_report_of_the_day(self):
        today = date(2026, 10, 21)
        first, stated = with_version(None, today, "v1.0.25-PL", "Staying on Cosy.")
        second, stated_again = with_version(stated, today, "v1.0.25-PL", "Staying on Cosy.")
        self.assertEqual(first, "v1.0.25-PL\n\nStaying on Cosy.")
        self.assertEqual(second, "Staying on Cosy.")
        self.assertEqual(stated_again, today)

    def test_a_clean_early_stay_is_silent(self):
        self.assertFalse(early_report_needed(None, "ensemble", True, False))

    def test_early_still_speaks_for_a_fallback_or_a_switch(self):
        self.assertTrue(early_report_needed(None, "slot-average", True, False))
        self.assertTrue(early_report_needed("no history", None, True, False))
        self.assertTrue(early_report_needed(None, "ensemble", False, False))
        self.assertTrue(early_report_needed(None, "ensemble", True, True))

    def test_an_early_switch_names_the_clock(self):
        self.assertEqual(
            hop_decision_line("cosy", False, 40, True, ["Agile"], "early", "23:00"),
            "Switching to Agile at 23:00.",
        )
        self.assertEqual(
            hop_decision_line("agile", False, -20, False, [], "final", "23:00"),
            "Staying on Agile. Tomorrow's Cosy switch waits until that day is metered.",
        )


if __name__ == "__main__":
    unittest.main()
