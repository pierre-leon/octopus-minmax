"""Half-hour features for the day-ahead consumption forecast.

Slot 0 is 00:00 and slot 47 is 23:30, on the UTC day the tariff rates are
queried with. Sine and cosine of the slot index put slot 47 next to slot 0.
Day-of-week is expanded to indicators so Sunday is not treated as larger
than Monday. Lags are counted in half-hours: t-1, t-2, t-48 and t-336.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


SLOTS = 48
LAG_WEEK = 336
HISTORY_DAYS = 365
CV_LOOKBACK_DAYS = 90
CV_FOLDS = 5
CV_TRAIN_DAYS = 21
CV_TEST_DAYS = 3
HORIZON_WEIGHT = 3.0
MIN_SLOTS = 40
HEATING_BASE_C = 15.5
COOLING_BASE_C = 22.0

DOW_COLUMNS = [f"dow_{i}" for i in range(7)]
CORE_COLUMNS = [
    "slot_sin", "slot_cos", "doy_sin", "doy_cos",
    "lag1", "lag2", "lag48", "lag336",
    *DOW_COLUMNS,
]
BEHAVIOR_COLUMNS = ["morning", "evening"]
WEATHER_COLUMNS = ["temperature", "solar", "humidity"]
THRESHOLD_COLUMNS = ["heating_degree", "cooling_degree"]
CANDIDATE_SETS = [
    CORE_COLUMNS,
    CORE_COLUMNS + BEHAVIOR_COLUMNS,
    CORE_COLUMNS + BEHAVIOR_COLUMNS + WEATHER_COLUMNS,
    CORE_COLUMNS + BEHAVIOR_COLUMNS + WEATHER_COLUMNS + THRESHOLD_COLUMNS,
]
FULL_COLUMNS = CANDIDATE_SETS[-1]

SEQ_CHANNELS = [
    "consumption",
    "temperature", "solar", "humidity",
    "heating_degree", "cooling_degree",
    "slot_sin", "slot_cos",
    "doy_sin", "doy_cos",
    "dow_sin", "dow_cos",
    "morning", "evening",
]
CONTINUOUS_CHANNELS = {
    "consumption", "temperature", "solar", "humidity",
    "heating_degree", "cooling_degree",
}

# Supply-region centres, used when the house coordinates are not set.
REGION_LATLON = {
    "A": (52.63, 1.30),
    "B": (52.95, -1.15),
    "C": (51.51, -0.13),
    "D": (53.41, -2.99),
    "E": (52.48, -1.89),
    "F": (54.98, -1.61),
    "G": (53.48, -2.24),
    "H": (50.90, -1.40),
    "J": (50.82, -0.14),
    "K": (51.48, -3.18),
    "L": (51.45, -2.59),
    "M": (53.80, -1.55),
    "N": (55.95, -3.19),
    "P": (57.15, -2.11),
}


def slot_cycle(slot: int) -> Tuple[float, float]:
    angle = 2 * math.pi * slot / SLOTS
    return math.sin(angle), math.cos(angle)


def doy_cycle(day: date) -> Tuple[float, float]:
    doy = min(day.timetuple().tm_yday, 365)
    angle = 2 * math.pi * doy / 365
    return math.sin(angle), math.cos(angle)


def slot_read_at(day: date, slot: int) -> str:
    hour, minute = divmod(slot * 30, 60)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00Z"


def profile_from_slots(day: date, values: np.ndarray) -> list:
    return [
        {"readAt": slot_read_at(day, slot), "consumptionDelta": float(max(values[slot], 0.0))}
        for slot in range(SLOTS)
    ]


def parse_moment(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def ingest_entries(entries: Sequence[dict]) -> Tuple[List[date], np.ndarray]:
    """Bin telemetry onto a continuous UTC-day grid of 48 half-hours."""
    buckets: Dict[date, np.ndarray] = {}
    for entry in entries:
        raw = entry.get("readAt")
        value = entry.get("consumptionDelta")
        if not raw or value is None:
            continue
        moment = parse_moment(raw)
        minute = 0 if moment.minute < 30 else 30
        slot = moment.hour * 2 + (1 if minute == 30 else 0)
        day_values = buckets.get(moment.date())
        if day_values is None:
            day_values = np.full(SLOTS, np.nan)
            buckets[moment.date()] = day_values
        day_values[slot] = float(value)
    if not buckets:
        return [], np.zeros((0, SLOTS))
    start, end = min(buckets), max(buckets)
    days = []
    rows = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        rows.append(buckets.get(cursor, np.full(SLOTS, np.nan)))
        cursor += timedelta(days=1)
    return days, np.vstack(rows)


def shift_slots(values: np.ndarray, steps: int) -> np.ndarray:
    flat = values.reshape(-1)
    shifted = np.full(flat.shape, np.nan)
    if 0 < steps < flat.size:
        shifted[steps:] = flat[:-steps]
    return shifted.reshape(values.shape)


def _broadcast_slots(row: np.ndarray, n_days: int) -> np.ndarray:
    return np.broadcast_to(row, (n_days, SLOTS)).copy()


def _broadcast_days(column: np.ndarray, n_days: int) -> np.ndarray:
    return np.broadcast_to(column.reshape(n_days, 1), (n_days, SLOTS)).copy()


def feature_cube(days: Sequence[date], grid: np.ndarray, weather: Optional[np.ndarray]) -> dict:
    """Named arrays shaped (days, 48). Weather is (days, 48, 3) or missing."""
    n_days = len(days)
    slots = np.arange(SLOTS)
    slot_angle = 2 * math.pi * slots / SLOTS
    doy = np.array([min(day.timetuple().tm_yday, 365) for day in days], dtype=float)
    doy_angle = 2 * math.pi * doy / 365
    dow = np.array([day.weekday() for day in days])
    dow_angle = 2 * math.pi * dow / 7
    if weather is None:
        weather = np.full((n_days, SLOTS, 3), np.nan)
    temp = weather[:, :, 0]
    heating = np.maximum(HEATING_BASE_C - temp, 0)
    cooling = np.maximum(temp - COOLING_BASE_C, 0)
    heating = heating.astype(float)
    cooling = cooling.astype(float)
    heating[~np.isfinite(temp)] = np.nan
    cooling[~np.isfinite(temp)] = np.nan
    cube = {
        "consumption": grid,
        "slot_sin": _broadcast_slots(np.sin(slot_angle), n_days),
        "slot_cos": _broadcast_slots(np.cos(slot_angle), n_days),
        "doy_sin": _broadcast_days(np.sin(doy_angle), n_days),
        "doy_cos": _broadcast_days(np.cos(doy_angle), n_days),
        "dow_sin": _broadcast_days(np.sin(dow_angle), n_days),
        "dow_cos": _broadcast_days(np.cos(dow_angle), n_days),
        "lag1": shift_slots(grid, 1),
        "lag2": shift_slots(grid, 2),
        "lag48": shift_slots(grid, 48),
        "lag336": shift_slots(grid, LAG_WEEK),
        "morning": _broadcast_slots(((slots >= 14) & (slots <= 18)).astype(float), n_days),
        "evening": _broadcast_slots(((slots >= 34) & (slots <= 42)).astype(float), n_days),
        "temperature": temp,
        "solar": weather[:, :, 1],
        "humidity": weather[:, :, 2],
        "heating_degree": heating,
        "cooling_degree": cooling,
    }
    for dow_i in range(7):
        cube[f"dow_{dow_i}"] = _broadcast_days((dow == dow_i).astype(float), n_days)
    return cube


def complete_day_indices(days: Sequence[date], grid: np.ndarray, before: Optional[date]) -> List[int]:
    """Days with a full meter trace, strictly before `before` when that is set."""
    chosen = []
    for index, day in enumerate(days):
        if before is not None and day >= before:
            continue
        if index < 7:
            continue
        if int(np.isfinite(grid[index]).sum()) >= MIN_SLOTS:
            chosen.append(index)
    return chosen


def daily_totals(grid: np.ndarray) -> np.ndarray:
    totals = np.nansum(grid, axis=1).astype(float)
    totals[np.isfinite(grid).sum(axis=1) < MIN_SLOTS] = np.nan
    return totals


def sample_weights(days: Sequence[date], grid: np.ndarray) -> np.ndarray:
    """Up-weight days that leave the seasonal mean by more than one standard deviation.

    The seasonal mean is a two-harmonic fit on day-of-year. The standard
    deviation is taken over the historical daily totals, and every slot of an
    extreme day gets weight max(1, |z|).
    """
    weights = np.ones(len(days), dtype=float)
    totals = daily_totals(grid)
    valid = np.isfinite(totals)
    if int(valid.sum()) < 21:
        return weights
    doy = np.array([min(day.timetuple().tm_yday, 365) for day in days], dtype=float)
    observed = totals[valid]
    angle = 2 * math.pi * doy[valid] / 365
    design = np.column_stack([
        np.ones(observed.size),
        np.sin(angle), np.cos(angle),
        np.sin(2 * angle), np.cos(2 * angle),
    ])
    coef, *_ = np.linalg.lstsq(design, observed, rcond=None)
    angle_all = 2 * math.pi * doy / 365
    seasonal = np.column_stack([
        np.ones(len(days)),
        np.sin(angle_all), np.cos(angle_all),
        np.sin(2 * angle_all), np.cos(2 * angle_all),
    ]) @ coef
    std = float(np.std(observed))
    if std < 1e-6:
        return weights
    z = (totals - seasonal) / std
    extreme = np.maximum(1.0, np.abs(z))
    extreme[~valid] = 1.0
    return extreme


def slot_training_frame(cube: dict, slot: int, columns: Sequence[str],
                        day_indices: Sequence[int], weights: np.ndarray):
    """Rows for one half-hour model. Weekly and daily lags have to be present."""
    indices = np.asarray(list(day_indices), dtype=int)
    if indices.size == 0:
        empty = np.zeros((0, len(columns)))
        return empty, np.zeros(0), np.zeros(0), np.zeros(len(columns))
    y = cube["consumption"][indices, slot]
    columns_at_slot = [cube[name][indices, slot] for name in columns]
    features = np.column_stack(columns_at_slot)
    mask = np.isfinite(y)
    for name in ("lag48", "lag336"):
        if name in columns:
            mask &= np.isfinite(features[:, list(columns).index(name)])
    medians = np.zeros(len(columns))
    for column in range(features.shape[1]):
        observed = features[mask, column]
        observed = observed[np.isfinite(observed)]
        median = float(np.median(observed)) if observed.size else 0.0
        medians[column] = median
        missing = ~np.isfinite(features[:, column])
        features[missing, column] = median
    return features[mask], y[mask], weights[indices][mask], medians


def design_row(grid: np.ndarray, day_index: int, slot: int, columns: Sequence[str],
               days: Sequence[date], weather: Optional[np.ndarray]) -> Optional[list]:
    """One feature row, reading lags from `grid` so a rolled forecast can fill them."""
    def at(offset: int) -> float:
        flat = day_index * SLOTS + slot - offset
        if flat < 0:
            return np.nan
        day_i, slot_i = divmod(flat, SLOTS)
        if day_i >= grid.shape[0]:
            return np.nan
        return float(grid[day_i, slot_i])

    lag48 = at(48)
    lag336 = at(LAG_WEEK)
    if not math.isfinite(lag48) or not math.isfinite(lag336):
        return None
    temp = solar = humidity = np.nan
    if weather is not None and 0 <= day_index < weather.shape[0]:
        temp, solar, humidity = (float(item) for item in weather[day_index, slot])
    heating = max(HEATING_BASE_C - temp, 0.0) if math.isfinite(temp) else np.nan
    cooling = max(temp - COOLING_BASE_C, 0.0) if math.isfinite(temp) else np.nan
    slot_sin, slot_cos = slot_cycle(slot)
    doy_sin, doy_cos = doy_cycle(days[day_index])
    dow = days[day_index].weekday()
    values = {
        "slot_sin": slot_sin,
        "slot_cos": slot_cos,
        "doy_sin": doy_sin,
        "doy_cos": doy_cos,
        "lag1": at(1),
        "lag2": at(2),
        "lag48": lag48,
        "lag336": lag336,
        "morning": 1.0 if 14 <= slot <= 18 else 0.0,
        "evening": 1.0 if 34 <= slot <= 42 else 0.0,
        "temperature": temp,
        "solar": solar,
        "humidity": humidity,
        "heating_degree": heating,
        "cooling_degree": cooling,
    }
    for dow_i in range(7):
        values[f"dow_{dow_i}"] = 1.0 if dow == dow_i else 0.0
    return [values[name] for name in columns]


def fill_medians(row: Sequence[float], medians: np.ndarray) -> np.ndarray:
    filled = np.array(row, dtype=float)
    missing = ~np.isfinite(filled)
    filled[missing] = medians[missing]
    return filled


def walk_forward_folds(indices: Sequence[int], lookback: int = CV_LOOKBACK_DAYS,
                       folds: int = CV_FOLDS, train_days: int = CV_TRAIN_DAYS,
                       test_days: int = CV_TEST_DAYS) -> List[Tuple[List[int], List[int]]]:
    """Backwards-rolling folds inside the recent window. Each test block is `test_days` long."""
    window = list(indices[-lookback:])
    folds_out = []
    test_end = len(window)
    for _ in range(folds):
        test_start = test_end - test_days
        train_end = test_start
        train_start = train_end - train_days
        if train_start < 0:
            break
        folds_out.append((window[train_start:train_end], window[test_start:test_end]))
        test_end = test_start
    return folds_out


def horizon_score(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Half-hour MAE with a 3x multiplier on the 1–3 day horizon."""
    day_mae = np.nanmean(np.abs(actual - predicted), axis=1)
    return float(np.mean(day_mae * HORIZON_WEIGHT))


def daily_kwh_error(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual_total = np.nansum(actual, axis=1)
    predicted_total = np.nansum(predicted, axis=1)
    return float(np.mean(np.abs(actual_total - predicted_total) / 1000.0))


def sequence_batch(cube: dict, target_indices: Sequence[int], weights: np.ndarray,
                   lookback: int = 7, require_target: bool = True):
    """Past `lookback` days as (samples, days, slots, channels), with the next day as the target.

    Prediction does not know the target day yet, so `require_target` can be off.
    """
    features = []
    targets = []
    sample_weight = []
    consumption = cube["consumption"]
    for index in target_indices:
        if index < lookback:
            continue
        target = consumption[index]
        if require_target and int(np.isfinite(target).sum()) < MIN_SLOTS:
            continue
        window = []
        usable = True
        for step in range(lookback, 0, -1):
            day = index - step
            if int(np.isfinite(consumption[day]).sum()) < 20:
                usable = False
                break
            window.append(np.column_stack([cube[name][day] for name in SEQ_CHANNELS]))
        if not usable:
            continue
        features.append(np.stack(window))
        targets.append(target)
        sample_weight.append(weights[index])
    if not features:
        empty = np.zeros((0, lookback, SLOTS, len(SEQ_CHANNELS)))
        return empty, np.zeros((0, SLOTS)), np.zeros(0)
    return np.stack(features), np.stack(targets), np.asarray(sample_weight, dtype=float)


def channel_stats(batch: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    means = np.zeros(len(SEQ_CHANNELS))
    stds = np.ones(len(SEQ_CHANNELS))
    for index, name in enumerate(SEQ_CHANNELS):
        if name not in CONTINUOUS_CHANNELS:
            continue
        values = batch[..., index]
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        means[index] = float(values.mean())
        deviation = float(values.std())
        stds[index] = deviation if deviation > 1e-6 else 1.0
    return means, stds


def scale_channels(batch: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    scaled = (batch - means) / stds
    scaled[~np.isfinite(scaled)] = 0.0
    return scaled


def scale_targets(targets: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    consumption_index = SEQ_CHANNELS.index("consumption")
    return (targets - means[consumption_index]) / stds[consumption_index]


def unscale_targets(predicted: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    consumption_index = SEQ_CHANNELS.index("consumption")
    return predicted * stds[consumption_index] + means[consumption_index]
