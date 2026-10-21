import math
import os
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np

from cnn_lstm import CnnLstm, _output_loss
from demand_features import (
    FULL_COLUMNS,
    SLOTS,
    design_row,
    feature_cube,
    horizon_score,
    ingest_entries,
    sample_weights,
    slot_cycle,
    slot_read_at,
    slot_training_frame,
    walk_forward_folds,
)
from demand_model import (
    TrainSettings,
    _fill_lookback,
    blend_predictions,
    forecast_consumption,
    load_consumption_history,
)


class FeatureTests(unittest.TestCase):
    def test_slot_47_is_adjacent_to_slot_0(self):
        def distance(left, right):
            return np.linalg.norm(np.array(slot_cycle(left)) - np.array(slot_cycle(right)))

        self.assertAlmostEqual(distance(47, 0), distance(0, 1))
        self.assertLess(distance(47, 0), distance(0, 10))

    def test_lags_follow_the_half_hour_index(self):
        days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(20)]
        grid = np.array([[day * 100 + slot for slot in range(SLOTS)] for day in range(20)], dtype=float)
        cube = feature_cube(days, grid, None)
        self.assertEqual(cube["lag1"][10, 5], 10 * 100 + 4)
        self.assertEqual(cube["lag2"][10, 5], 10 * 100 + 3)
        self.assertEqual(cube["lag48"][10, 5], 9 * 100 + 5)
        self.assertEqual(cube["lag336"][10, 5], 3 * 100 + 5)
        self.assertEqual(cube["lag1"][10, 0], 9 * 100 + 47)
        self.assertEqual(cube["lag2"][10, 0], 9 * 100 + 46)
        self.assertEqual(cube["morning"][0, 14], 1)
        self.assertEqual(cube["morning"][0, 13], 0)
        self.assertEqual(cube["evening"][0, 34], 1)
        self.assertEqual(cube["evening"][0, 43], 0)

    def test_design_row_matches_the_cube(self):
        days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(20)]
        grid = np.array([[day * 100 + slot for slot in range(SLOTS)] for day in range(20)], dtype=float)
        weather = np.zeros((20, SLOTS, 3))
        weather[:, :, 0] = 10
        cube = feature_cube(days, grid, weather)
        row = design_row(grid, 10, 5, FULL_COLUMNS, days, weather)
        for name, value in zip(FULL_COLUMNS, row):
            self.assertAlmostEqual(value, cube[name][10, 5], places=6)

    def test_extreme_days_are_upweighted(self):
        days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(40)]
        grid = np.full((40, SLOTS), 20.0)
        grid[30] = 400.0
        weights = sample_weights(days, grid)
        self.assertEqual(weights[0], 1)
        self.assertGreater(weights[30], 1)

    def test_walk_forward_is_three_day_blocks_weighted_by_three(self):
        folds = walk_forward_folds(list(range(100)))
        self.assertEqual(len(folds), 5)
        train, test = folds[0]
        self.assertEqual(len(train), 21)
        self.assertEqual(test, [97, 98, 99])
        actual = np.zeros((3, SLOTS))
        predicted = np.ones((3, SLOTS))
        self.assertAlmostEqual(horizon_score(actual, predicted), 3.0)

    def test_training_frame_keeps_a_row_only_when_weekly_lag_exists(self):
        days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(20)]
        grid = np.arange(20 * SLOTS, dtype=float).reshape(20, SLOTS)
        cube = feature_cube(days, grid, None)
        features, target, _weights, _medians = slot_training_frame(
            cube, 3, ["lag1", "lag48", "lag336"], list(range(20)), np.ones(20),
        )
        self.assertEqual(len(target), 20 - 7)
        self.assertTrue(np.isfinite(features).all())


class NetworkTests(unittest.TestCase):
    def test_dense_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(2)
        net = CnnLstm(n_channels=2, n_slots=4, hidden=3, conv_channels=2, kernel=3, seed=1)
        sequences = rng.normal(size=(2, 3, 4, 2))
        targets = rng.normal(size=(2, 4))
        weights = np.ones(2)
        predicted, cache = net._forward(sequences)
        _loss, grad = _output_loss(predicted, targets, weights)
        grads = net._backward(cache, grad)
        epsilon = 1e-4
        original = net.params["dense_w"][0, 0]
        net.params["dense_w"][0, 0] = original + epsilon
        plus, _cache = net._forward(sequences)
        net.params["dense_w"][0, 0] = original - epsilon
        minus, _cache = net._forward(sequences)
        net.params["dense_w"][0, 0] = original
        numerical = (_output_loss(plus, targets, weights)[0] - _output_loss(minus, targets, weights)[0]) / (2 * epsilon)
        self.assertAlmostEqual(grads["dense_w"][0, 0], numerical, places=4)

    def test_training_reduces_loss_on_a_repeated_spike(self):
        spike = np.zeros(8)
        spike[3] = 1.0
        sequences = np.stack([
            np.stack([np.column_stack([spike, spike * 0.2]) for _day in range(4)])
            for _sample in range(6)
        ])
        targets = np.stack([spike for _sample in range(6)])
        net = CnnLstm(n_channels=2, n_slots=8, hidden=8, conv_channels=4, kernel=3, seed=0)
        before, _cache = net._forward(sequences)
        start = _output_loss(before, targets, np.ones(6))[0]
        finish = net.train(sequences, targets, np.ones(6), epochs=25, lr=5e-3)
        self.assertLess(finish, start * 0.5)


class ForecastTests(unittest.TestCase):
    def test_a_short_sunday_does_not_block_saturday(self):
        # Rows are Sat, Sun, Mon. Sunday is empty. Monday should still see Saturday.
        consumption = np.full((3, SLOTS), np.nan)
        consumption[0] = 10.0
        consumption[2, 0] = 3.0
        _fill_lookback(consumption, target_index=3, lookback=3)
        self.assertEqual(consumption[1, 5], 10.0)
        self.assertEqual(consumption[2, 5], 10.0)
        self.assertEqual(consumption[2, 0], 3.0)

    def test_blend_is_an_equal_average(self):
        blended = blend_predictions(
            np.array([0.0, 4.0]),
            np.array([0.0, 8.0]),
            np.array([10.0, 0.0]),
        )
        np.testing.assert_allclose(blended, [5.0, 3.0])

    def test_history_cache_refreshes_the_week_before_tomorrow(self):
        today = date(2026, 10, 10)
        calls = []

        def fetch(start, end):
            calls.append((start, end))
            return [{"readAt": slot_read_at(start, 0), "consumptionDelta": 5}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "history.json")
            first = load_consumption_history("meter", fetch, today, path, history_days=10)
            self.assertEqual(calls[0], (today - timedelta(days=10), today))
            self.assertEqual(len(first), 1)
            load_consumption_history("meter", fetch, today, path, history_days=10)
            self.assertEqual(calls[1][0], today - timedelta(days=6))

    def test_ensemble_forecasts_48_slots(self):
        start = date(2026, 1, 1)
        n_days = 70
        entries = []
        for offset in range(n_days):
            day = start + timedelta(days=offset)
            for slot in range(SLOTS):
                evening = 80.0 if 34 <= slot <= 42 else 0.0
                weekend = 25.0 if day.weekday() >= 5 else 0.0
                value = 40.0 + evening + weekend + 8.0 * math.sin(2 * math.pi * slot / SLOTS)
                entries.append({"readAt": slot_read_at(day, slot), "consumptionDelta": value})
        today = start + timedelta(days=n_days)
        target = today + timedelta(days=1)
        weather = np.full((n_days + 2, SLOTS, 3), 10.0)
        weather[:, :, 1] = 50
        weather[:, :, 2] = 70
        settings = TrainSettings(
            min_days=28, lgb_rounds=8, cat_rounds=8, cold_epochs=1,
            finetune_epochs=1, run_selection=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            profile, info = forecast_consumption(
                entries, target, "C", today=today, weather=weather,
                model_dir=tmp, settings=settings, cache_weather=False,
            )
            again, again_info = forecast_consumption(
                entries, target, "C", today=today, weather=weather,
                model_dir=tmp, settings=settings, cache_weather=False,
            )
        self.assertEqual(again_info["method"], "ensemble")
        self.assertEqual(
            [row["consumptionDelta"] for row in again],
            [row["consumptionDelta"] for row in profile],
        )
        self.assertEqual(info["method"], "ensemble")
        self.assertEqual(len(profile), 48)
        self.assertTrue(all(row["consumptionDelta"] >= 0 for row in profile))
        self.assertTrue(all(row["readAt"].startswith(target.isoformat()) for row in profile))
        evening = [row["consumptionDelta"] for row in profile if row["readAt"].endswith("T18:00:00Z")][0]
        night = [row["consumptionDelta"] for row in profile if row["readAt"].endswith("T03:00:00Z")][0]
        self.assertGreater(evening, night)


if __name__ == "__main__":
    unittest.main()
