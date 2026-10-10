import unittest
from datetime import date

from hop import decide_hop, predicted_consumption, saving_pence


class DecideHopTests(unittest.TestCase):
    def test_agile_today_and_tomorrow_stay(self):
        self.assertEqual(decide_hop("agile", False, False), [])

    def test_agile_today_cosy_tomorrow_stay(self):
        # Tomorrow can be repaired after it has been metered.
        self.assertEqual(decide_hop("agile", False, False), [])
        self.assertEqual(decide_hop("agile", False, True), [])

    def test_agile_today_cosy_better_switches_to_cosy(self):
        self.assertEqual(decide_hop("agile", True, False), ["cosy"])

    def test_agile_today_cosy_tomorrow_agile_switches_twice(self):
        self.assertEqual(decide_hop("agile", True, True), ["cosy", "agile"])

    def test_cosy_tomorrow_agile_switches(self):
        self.assertEqual(decide_hop("cosy", False, True), ["agile"])
        self.assertEqual(decide_hop("cosy", True, True), ["agile"])

    def test_cosy_tomorrow_cosy_stays(self):
        self.assertEqual(decide_hop("cosy", False, False), [])
        self.assertEqual(decide_hop("cosy", True, False), [])

    def test_other_tariffs_are_left_alone(self):
        self.assertEqual(decide_hop("go", True, True), [])


class PredictionTests(unittest.TestCase):
    def test_averages_the_same_clock_time_onto_the_target_day(self):
        history = [
            {"readAt": "2026-10-01T00:30:00+00:00", "consumptionDelta": 100},
            {"readAt": "2026-10-02T00:30:00+00:00", "consumptionDelta": 300},
            {"readAt": "2026-10-01T01:00:00Z", "consumptionDelta": 50},
        ]
        predicted = predicted_consumption(history, date(2026, 10, 11))
        self.assertEqual(predicted, [
            {"readAt": "2026-10-11T00:30:00Z", "consumptionDelta": 200},
            {"readAt": "2026-10-11T01:00:00Z", "consumptionDelta": 50},
        ])

    def test_saving_pence(self):
        self.assertEqual(saving_pence(100, 40), 60)
        self.assertIsNone(saving_pence(None, 40))


if __name__ == "__main__":
    unittest.main()
