"""Day-ahead half-hour forecast.

Model A is 48 slot models, each an equal average of LightGBM and CatBoost.
Model B is a CNN-LSTM that reads the previous week and emits all 48 slots.
The forecast is the equal average of A and B. Trees gain a few estimators
each night; the network is fine-tuned for a few epochs on the last 14 days.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, timedelta
from typing import Callable, List, Optional, Sequence

import numpy as np

from cnn_lstm import CnnLstm
from demand_features import (
    CANDIDATE_SETS,
    FULL_COLUMNS,
    HISTORY_DAYS,
    REGION_LATLON,
    SEQ_CHANNELS,
    SLOTS,
    channel_stats,
    complete_day_indices,
    daily_kwh_error,
    design_row,
    feature_cube,
    fill_medians,
    horizon_score,
    ingest_entries,
    profile_from_slots,
    sample_weights,
    scale_channels,
    scale_targets,
    sequence_batch,
    slot_training_frame,
    unscale_targets,
    walk_forward_folds,
)
from hop import history_day_count, predicted_consumption

logger = logging.getLogger("octobot.demand")

_lock = threading.Lock()
ARCH_VERSION = 1
LOOKBACK_DAYS = 7
FINETUNE_DAYS = 14
SELECTION_INTERVAL_DAYS = 7


class TrainSettings:
    def __init__(self, min_days: int = 28, lgb_rounds: int = 80, lgb_increment: int = 20,
                 cat_rounds: int = 80, cat_increment: int = 20, max_trees: int = 250,
                 num_leaves: int = 15, cat_depth: int = 4, cold_epochs: int = 8,
                 finetune_epochs: int = 3, run_selection: bool = True,
                 selection_rounds: int = 25):
        self.min_days = min_days
        self.lgb_rounds = lgb_rounds
        self.lgb_increment = lgb_increment
        self.cat_rounds = cat_rounds
        self.cat_increment = cat_increment
        self.max_trees = max_trees
        self.num_leaves = num_leaves
        self.cat_depth = cat_depth
        self.cold_epochs = cold_epochs
        self.finetune_epochs = finetune_epochs
        self.run_selection = run_selection
        self.selection_rounds = selection_rounds


def data_dir() -> str:
    if os.path.isdir("/data"):
        return "/data"
    os.makedirs("data", exist_ok=True)
    return "data"


def blend_predictions(lightgbm_slots: np.ndarray, catboost_slots: np.ndarray,
                      sequence_slots: np.ndarray) -> np.ndarray:
    model_a = 0.5 * (lightgbm_slots + catboost_slots)
    return np.maximum(0.5 * model_a + 0.5 * sequence_slots, 0.0)


def load_consumption_history(device_id: str, fetch_between: Callable, today: Optional[date] = None,
                             cache_path: Optional[str] = None, history_days: int = HISTORY_DAYS) -> list:
    """Cached half-hours through today. The last two days are always re-read."""
    today = today or date.today()
    start = today - timedelta(days=history_days)
    path = cache_path or os.path.join(data_dir(), "demand_history.json")
    cached = _read_history_cache(path, device_id)
    fetch_start = start if not cached else max(start, today - timedelta(days=2))
    try:
        fresh = fetch_between(fetch_start, today)
    except Exception as exc:
        if not cached:
            raise
        logger.warning(f"Consumption history refresh failed, using the cache: {exc}")
        fresh = []
    for entry in fresh:
        read_at = entry.get("readAt")
        if read_at and entry.get("consumptionDelta") is not None:
            cached[read_at] = entry["consumptionDelta"]
    from demand_features import parse_moment
    kept = {}
    for read_at, value in cached.items():
        try:
            day = parse_moment(read_at).date()
        except ValueError:
            continue
        if day >= start:
            kept[read_at] = value
    _write_history_cache(path, device_id, kept)
    return [{"readAt": read_at, "consumptionDelta": value} for read_at, value in kept.items()]


def forecast_consumption(entries: Sequence[dict], target_day: date, region_code: str,
                         latitude: Optional[float] = None, longitude: Optional[float] = None,
                         today: Optional[date] = None, weather: Optional[np.ndarray] = None,
                         model_dir: Optional[str] = None, settings: Optional[TrainSettings] = None,
                         cache_weather: bool = True) -> tuple:
    """48 half-hours for `target_day`, plus a short description of how they were made."""
    settings = settings or TrainSettings()
    today = today or date.today()
    days, grid = ingest_entries(entries)
    info = {
        "days": history_day_count(entries),
        "method": "slot-average",
        "detail": "",
        "walk_forward_daily_kwh": None,
    }
    if grid.size == 0:
        info["detail"] = "No consumption history."
        return [], info
    trainable = complete_day_indices(days, grid, before=today)
    if len(trainable) < settings.min_days or not _trees_available():
        info["detail"] = _fallback_reason(len(trainable), settings.min_days)
        return predicted_consumption(entries, target_day), info

    try:
        with _lock:
            profile, trained = _ensemble_profile(
                days, grid, trainable, target_day, region_code,
                latitude, longitude, weather, model_dir, settings, cache_weather, info,
            )
    except Exception as exc:
        logger.exception(f"Day-ahead ensemble failed, using the slot average: {exc}")
        info["detail"] = str(exc)
        return predicted_consumption(entries, target_day), info
    if profile is None:
        info["detail"] = trained or "The ensemble did not produce a day."
        return predicted_consumption(entries, target_day), info
    info["method"] = "ensemble"
    info["days"] = len(trainable)
    return profile, info


def _ensemble_profile(days, grid, trainable, target_day, region_code, latitude, longitude,
                      weather, model_dir, settings, cache_weather, info):
    directory = model_dir or os.path.join(data_dir(), "demand_model")
    os.makedirs(directory, exist_ok=True)
    dates = _dates_through(days, target_day)
    if weather is None:
        weather = _weather_grid(dates, region_code, latitude, longitude, cache_weather)
    elif weather.shape[0] != len(dates):
        raise ValueError("weather rows must cover history through the target day")
    cube = feature_cube(dates, _grid_through(days, grid, dates), weather)
    cube["__dates"] = dates
    aligned = cube["consumption"]
    weights = sample_weights(dates, aligned)
    meta = _read_meta(directory)
    through = dates[-2] if len(dates) >= 2 else None
    # The last row is the target day, which has no consumption yet.
    fresh = (
        meta
        and meta.get("version") == ARCH_VERSION
        and meta.get("trained_through") == (through.isoformat() if through else "")
        and _model_files_present(directory)
    )
    if not fresh:
        columns, num_leaves, cat_depth, score_wh, score_kwh = _choose_configuration(
            cube, weights, trainable, dates, settings, meta,
        )
        _fit_all(
            cube, weights, trainable, dates, columns, num_leaves, cat_depth,
            directory, settings, meta, through, score_wh, score_kwh,
        )
        meta = _read_meta(directory)
    columns = meta["features"]
    medians = np.asarray(meta["medians"], dtype=float)
    info["walk_forward_daily_kwh"] = meta.get("walk_forward_daily_kwh")
    target_index = dates.index(target_day)
    tree_lgb, tree_cat = _predict_trees(aligned, dates, weather, target_index, columns, medians, directory)
    sequence = _predict_sequence(cube, target_index, directory)
    blended = blend_predictions(tree_lgb, tree_cat, sequence)
    logger.info(
        f"Day-ahead ensemble for {target_day.isoformat()} "
        f"from {len(trainable)} days, about {float(blended.sum()) / 1000:.2f} kWh"
    )
    return profile_from_slots(target_day, blended), None


def _choose_configuration(cube, weights, trainable, dates, settings, meta):
    defaults = (FULL_COLUMNS, settings.num_leaves, settings.cat_depth, None, None)
    if not settings.run_selection:
        if meta and meta.get("features"):
            return (
                meta["features"], meta.get("num_leaves", settings.num_leaves),
                meta.get("cat_depth", settings.cat_depth),
                meta.get("walk_forward_wh"), meta.get("walk_forward_daily_kwh"),
            )
        return defaults
    if meta and meta.get("features") and not _selection_stale(meta, dates):
        return (
            meta["features"], meta.get("num_leaves", settings.num_leaves),
            meta.get("cat_depth", settings.cat_depth),
            meta.get("walk_forward_wh"), meta.get("walk_forward_daily_kwh"),
        )
    folds = walk_forward_folds(trainable)
    if len(folds) < 3:
        logger.info("Not enough history for walk-forward selection; using the full feature set.")
        return defaults
    best_columns = FULL_COLUMNS
    best_score = None
    best_daily = None
    for columns in CANDIDATE_SETS:
        scored = _score_lgb(cube, weights, columns, folds, settings.selection_rounds, settings.num_leaves)
        if scored is None:
            continue
        score, daily = scored
        logger.info(f"Walk-forward feature score {score:.2f} Wh for {len(columns)} columns")
        if best_score is None or score < best_score * 0.98:
            best_score = score
            best_daily = daily
            best_columns = columns
    num_leaves = settings.num_leaves
    leaf_score = best_score
    for leaves in (7, 15, 31):
        scored = _score_lgb(cube, weights, best_columns, folds, settings.selection_rounds, leaves)
        if scored is None:
            continue
        score, daily = scored
        if leaf_score is None or score < leaf_score:
            leaf_score = score
            num_leaves = leaves
            best_daily = daily
            best_score = score
    cat_depth = _choose_depth(cube, weights, best_columns, folds, settings)
    logger.info(
        f"Selected {len(best_columns)} features, {num_leaves} leaves, depth {cat_depth}"
    )
    return best_columns, num_leaves, cat_depth, best_score, best_daily


def _score_lgb(cube, weights, columns, folds, rounds, num_leaves):
    scores = []
    daily = []
    for train_idx, test_idx in folds:
        models = []
        medians = []
        for slot in range(SLOTS):
            features, target, weight, median = slot_training_frame(
                cube, slot, columns, train_idx, weights,
            )
            if len(target) < 8:
                return None
            models.append(_fit_lgb(features, target, weight, rounds, num_leaves))
            medians.append(median)
        actual, predicted = _replay_days(
            cube, cube["__dates"], test_idx, columns, medians,
            lambda slot, row, models=models: float(models[slot].predict(row.reshape(1, -1))[0]),
        )
        scores.append(horizon_score(actual, predicted))
        daily.append(daily_kwh_error(actual, predicted))
    return float(np.mean(scores)), float(np.mean(daily))


def _choose_depth(cube, weights, columns, folds, settings) -> int:
    probe_slots = [8, 14, 20, 34, 38, 42]
    best_depth = settings.cat_depth
    best_score = None
    for depth in (4, 6):
        scores = []
        usable = True
        for train_idx, test_idx in folds:
            models = {}
            medians = {}
            for slot in probe_slots:
                features, target, weight, median = slot_training_frame(
                    cube, slot, columns, train_idx, weights,
                )
                if len(target) < 8:
                    usable = False
                    break
                models[slot] = _fit_cat(features, target, weight, settings.selection_rounds, depth)
                medians[slot] = median
            if not usable:
                break
            actual_rows = []
            predicted_rows = []
            for day_index in test_idx:
                row_actual = []
                row_pred = []
                for slot in probe_slots:
                    row_actual.append(cube["consumption"][day_index, slot])
                    features, _target, _weight, _median = slot_training_frame(
                        cube, slot, columns, [day_index], np.ones(cube["consumption"].shape[0]),
                    )
                    if len(features) == 0:
                        row_pred.append(np.nan)
                    else:
                        row_pred.append(float(models[slot].predict(features[:1])[0]))
                actual_rows.append(row_actual)
                predicted_rows.append(row_pred)
            scores.append(horizon_score(np.asarray(actual_rows), np.asarray(predicted_rows)))
        if usable and scores:
            score = float(np.mean(scores))
            if best_score is None or score < best_score:
                best_score = score
                best_depth = depth
    return best_depth


def _fit_all(cube, weights, trainable, dates, columns, num_leaves, cat_depth,
             directory, settings, previous, through, score_wh, score_kwh):
    continuing = (
        previous
        and previous.get("version") == ARCH_VERSION
        and previous.get("features") == list(columns)
        and previous.get("num_leaves") == num_leaves
        and previous.get("cat_depth") == cat_depth
        and _model_files_present(directory)
    )
    medians = []
    os.makedirs(os.path.join(directory, "lgb"), exist_ok=True)
    os.makedirs(os.path.join(directory, "cat"), exist_ok=True)
    logger.info(
        f"{'Updating' if continuing else 'Training'} day-ahead trees on {len(trainable)} days"
    )
    recent = trainable[-90:]
    for slot in range(SLOTS):
        full_x, full_y, full_w, full_median = slot_training_frame(
            cube, slot, columns, trainable, weights,
        )
        medians.append(full_median.tolist())
        if len(full_y) < 8:
            raise RuntimeError(f"Slot {slot} does not have enough history to train")
        lgb_path = os.path.join(directory, "lgb", f"{slot}.txt")
        cat_path = os.path.join(directory, "cat", f"{slot}.cbm")
        lgb_init = _load_lgb(lgb_path) if continuing else None
        cat_init = _load_cat(cat_path) if continuing else None
        if lgb_init is not None and _tree_count(lgb_init) >= settings.max_trees:
            lgb_init = None
        if cat_init is not None and _tree_count(cat_init) >= settings.max_trees:
            cat_init = None
        # New trees fit the last 90 days. A cold start, or a rebuild past the
        # tree cap, sees the whole year.
        if lgb_init is not None:
            features, target, weight, median = slot_training_frame(
                cube, slot, columns, recent, weights,
            )
            medians[-1] = median.tolist()
            booster = _fit_lgb(
                features, target, weight, settings.lgb_increment, num_leaves, lgb_init,
            )
        else:
            booster = _fit_lgb(full_x, full_y, full_w, settings.lgb_rounds, num_leaves)
        _save_trained(booster, lgb_path)
        if cat_init is not None:
            features, target, weight, _median = slot_training_frame(
                cube, slot, columns, recent, weights,
            )
            cat_model = _fit_cat(
                features, target, weight, settings.cat_increment, cat_depth, cat_init,
            )
        else:
            cat_model = _fit_cat(full_x, full_y, full_w, settings.cat_rounds, cat_depth)
        _save_trained(cat_model, cat_path)
    _fit_sequence(cube, weights, trainable, directory, settings, continuing)
    meta = {
        "version": ARCH_VERSION,
        "trained_through": through.isoformat() if through else "",
        "features": list(columns),
        "num_leaves": num_leaves,
        "cat_depth": cat_depth,
        "selected_on": (through or date.today()).isoformat(),
        "walk_forward_wh": None if score_wh is None else float(score_wh),
        "walk_forward_daily_kwh": (
            float(score_kwh) if score_kwh is not None
            else (previous or {}).get("walk_forward_daily_kwh")
        ),
        "medians": medians,
    }
    if continuing and previous and previous.get("selected_on") and not _selection_stale(previous, dates):
        meta["selected_on"] = previous["selected_on"]
    _write_meta(directory, meta)


def _fit_sequence(cube, weights, trainable, directory, settings, continuing: bool):
    path = os.path.join(directory, "lstm.npz")
    network = CnnLstm(n_channels=len(SEQ_CHANNELS), n_slots=SLOTS)
    if continuing and os.path.isfile(path):
        network.load(path)
        with np.load(path) as stats:
            means = stats["channel_mean"].copy()
            stds = stats["channel_std"].copy()
        recent_targets = [index for index in trainable if index >= trainable[-1] - (FINETUNE_DAYS - 1)]
        epochs = settings.finetune_epochs
        target_indices = recent_targets[-FINETUNE_DAYS:]
        sequences, targets, sample_weight = sequence_batch(cube, target_indices, weights, LOOKBACK_DAYS)
    else:
        epochs = settings.cold_epochs
        sequences, targets, sample_weight = sequence_batch(cube, trainable, weights, LOOKBACK_DAYS)
        means, stds = channel_stats(sequences)
    if len(sequences) == 0:
        if continuing:
            logger.warning("Skipping CNN-LSTM fine-tune; the last two weeks are incomplete.")
            return
        raise RuntimeError("No weekly sequences to train the CNN-LSTM")
    scaled = scale_channels(sequences, means, stds)
    scaled_targets = scale_targets(targets, means, stds)
    loss = network.train(scaled, scaled_targets, sample_weight, epochs=epochs)
    if not np.isfinite(loss):
        raise RuntimeError("CNN-LSTM training diverged")
    network.save(path)
    with np.load(path) as payload:
        stored = {key: payload[key].copy() for key in payload.files}
    stored["channel_mean"] = means
    stored["channel_std"] = stds
    np.savez(path, **stored)


def _predict_trees(grid, dates, weather, target_index, columns, medians, directory):
    lightgbm_slots = np.zeros(SLOTS)
    catboost_slots = np.zeros(SLOTS)
    working = grid.copy()
    for slot in range(SLOTS):
        row = design_row(working, target_index, slot, columns, dates, weather)
        if row is None:
            lightgbm_slots[slot] = _slot_median(grid, slot)
            catboost_slots[slot] = lightgbm_slots[slot]
        else:
            filled = fill_medians(row, medians[slot])
            booster = _load_lgb(os.path.join(directory, "lgb", f"{slot}.txt"))
            cat_model = _load_cat(os.path.join(directory, "cat", f"{slot}.cbm"))
            lightgbm_slots[slot] = max(float(booster.predict(filled.reshape(1, -1))[0]), 0.0)
            catboost_slots[slot] = max(float(cat_model.predict(filled.reshape(1, -1))[0]), 0.0)
        # Later slots see this slot's tree average as their short-term lag.
        working[target_index, slot] = 0.5 * (lightgbm_slots[slot] + catboost_slots[slot])
    return lightgbm_slots, catboost_slots


def _predict_sequence(cube, target_index, directory) -> np.ndarray:
    weights = np.ones(cube["consumption"].shape[0])
    usable = dict(cube)
    consumption = cube["consumption"].copy()
    # The run is in the evening, but a missing hour should not drop the whole week.
    for day in range(target_index - 1, max(-1, target_index - LOOKBACK_DAYS - 1), -1):
        if day <= 0:
            break
        if int(np.isfinite(consumption[day]).sum()) >= 20:
            continue
        missing = ~np.isfinite(consumption[day])
        consumption[day, missing] = consumption[day - 1, missing]
    usable["consumption"] = consumption
    sequences, _targets, _weights = sequence_batch(
        usable, [target_index], weights, LOOKBACK_DAYS, require_target=False,
    )
    if len(sequences) == 0:
        raise RuntimeError("The week before the target day is too incomplete for the CNN-LSTM")
    path = os.path.join(directory, "lstm.npz")
    stats = np.load(path)
    means, stds = stats["channel_mean"], stats["channel_std"]
    network = CnnLstm(n_channels=len(SEQ_CHANNELS), n_slots=SLOTS)
    network.load(path)
    scaled = scale_channels(sequences, means, stds)
    predicted = network.predict(scaled)
    return np.maximum(unscale_targets(predicted, means, stds)[0], 0.0)


def _replay_days(cube, dates, day_indices, columns, medians, predict_slot):
    actual = []
    predicted = []
    base = cube["consumption"]
    weather = np.stack([cube["temperature"], cube["solar"], cube["humidity"]], axis=2)
    for day_index in day_indices:
        working = base.copy()
        working[day_index] = np.nan
        hats = np.zeros(SLOTS)
        for slot in range(SLOTS):
            row = design_row(working, day_index, slot, columns, dates, weather)
            if row is None:
                hats[slot] = _slot_median(base, slot)
            else:
                hats[slot] = max(float(predict_slot(slot, fill_medians(row, medians[slot]))), 0.0)
            working[day_index, slot] = hats[slot]
        actual.append(base[day_index])
        predicted.append(hats)
    return np.vstack(actual), np.vstack(predicted)


def _slot_median(grid: np.ndarray, slot: int) -> float:
    column = grid[:, slot]
    column = column[np.isfinite(column)]
    if column.size == 0:
        return 0.0
    return float(np.median(column))


def _dates_through(days: Sequence[date], target_day: date) -> List[date]:
    start = days[0]
    end = max(days[-1], target_day)
    cursor = start
    dates = []
    while cursor <= end:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def _grid_through(days: Sequence[date], grid: np.ndarray, dates: Sequence[date]) -> np.ndarray:
    by_day = {day: grid[index] for index, day in enumerate(days)}
    return np.vstack([by_day.get(day, np.full(SLOTS, np.nan)) for day in dates])


def _selection_stale(meta: dict, dates: Sequence[date]) -> bool:
    raw = meta.get("selected_on")
    if not raw:
        return True
    selected = date.fromisoformat(raw)
    latest = dates[-2] if len(dates) >= 2 else dates[-1]
    return (latest - selected).days >= SELECTION_INTERVAL_DAYS


def _fallback_reason(days: int, minimum: int) -> str:
    if not _trees_available():
        return "LightGBM and CatBoost are not installed, so the slot average is used."
    return f"Only {days} complete days are available; the ensemble wants at least {minimum}."


def _trees_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        import catboost  # noqa: F401
    except ImportError:
        return False
    return True


class _ConstantModel:
    """A slot whose history never moves. Both tree libraries refuse that target."""

    def __init__(self, value: float):
        self.value = float(value)

    def predict(self, features):
        rows = 1 if np.ndim(features) == 1 else len(features)
        return np.full(rows, self.value)

    def num_trees(self) -> int:
        return 0

    @property
    def tree_count_(self) -> int:
        return 0

    def save_model(self, path: str) -> None:
        if os.path.isfile(path):
            os.remove(path)
        with open(_const_path(path), "w", encoding="utf-8") as handle:
            json.dump({"value": self.value}, handle)


def _const_path(path: str) -> str:
    return f"{path}.const"


def _save_trained(model, path: str) -> None:
    if isinstance(model, _ConstantModel):
        model.save_model(path)
        return
    const_path = _const_path(path)
    if os.path.isfile(const_path):
        os.remove(const_path)
    model.save_model(path)


def _fit_lgb(features, target, weight, rounds, num_leaves, init=None):
    if isinstance(init, _ConstantModel):
        init = None
    if len(target) == 0 or float(np.std(target)) < 1e-8:
        return _ConstantModel(float(np.mean(target)) if len(target) else 0.0)
    import lightgbm as lgb
    try:
        dataset = lgb.Dataset(features, label=target, weight=weight, free_raw_data=False)
        params = {
            "objective": "regression",
            "learning_rate": 0.05,
            "num_leaves": num_leaves,
            "min_data_in_leaf": 5,
            "verbosity": -1,
            "num_threads": 1,
            "force_col_wise": True,
            "feature_pre_filter": False,
        }
        return lgb.train(params, dataset, num_boost_round=rounds, init_model=init)
    except Exception as exc:
        logger.warning(f"LightGBM fit failed ({exc}); using the slot mean.")
        if init is not None:
            return init
        return _ConstantModel(float(np.mean(target)))


def _fit_cat(features, target, weight, rounds, depth, init=None):
    if isinstance(init, _ConstantModel):
        init = None
    if len(target) == 0 or float(np.std(target)) < 1e-8:
        return _ConstantModel(float(np.mean(target)) if len(target) else 0.0)
    from catboost import CatBoostRegressor
    try:
        model = CatBoostRegressor(
            iterations=rounds,
            depth=depth,
            learning_rate=0.05,
            loss_function="RMSE",
            thread_count=1,
            allow_writing_files=False,
            verbose=False,
        )
        model.fit(features, target, sample_weight=weight, init_model=init)
        return model
    except Exception as exc:
        logger.warning(f"CatBoost fit failed ({exc}); using the slot mean.")
        if init is not None:
            return init
        return _ConstantModel(float(np.mean(target)))


def _load_lgb(path: str):
    const_path = _const_path(path)
    if os.path.isfile(const_path) and not os.path.isfile(path):
        with open(const_path, "r", encoding="utf-8") as handle:
            return _ConstantModel(json.load(handle)["value"])
    import lightgbm as lgb
    return lgb.Booster(model_file=path)


def _load_cat(path: str):
    const_path = _const_path(path)
    if os.path.isfile(const_path) and not os.path.isfile(path):
        with open(const_path, "r", encoding="utf-8") as handle:
            return _ConstantModel(json.load(handle)["value"])
    from catboost import CatBoostRegressor
    model = CatBoostRegressor()
    model.load_model(path)
    return model


def _tree_count(model) -> int:
    if hasattr(model, "num_trees"):
        return int(model.num_trees())
    return int(model.tree_count_)


def _model_files_present(directory: str) -> bool:
    if not os.path.isfile(os.path.join(directory, "lstm.npz")):
        return False
    for slot in range(SLOTS):
        lgb_path = os.path.join(directory, "lgb", f"{slot}.txt")
        cat_path = os.path.join(directory, "cat", f"{slot}.cbm")
        if not (os.path.isfile(lgb_path) or os.path.isfile(_const_path(lgb_path))):
            return False
        if not (os.path.isfile(cat_path) or os.path.isfile(_const_path(cat_path))):
            return False
    return True


def _read_meta(directory: str) -> Optional[dict]:
    path = os.path.join(directory, "meta.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Ignoring the saved demand model: {exc}")
        return None


def _write_meta(directory: str, meta: dict) -> None:
    path = os.path.join(directory, "meta.json")
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(meta, handle)
    os.replace(temporary, path)


def _read_history_cache(path: str, device_id: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("device_id") != device_id:
        return {}
    return dict(payload.get("entries") or {})


def _write_history_cache(path: str, device_id: str, entries: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"device_id": device_id, "entries": entries}, handle)
    os.replace(temporary, path)


def _weather_grid(dates: Sequence[date], region_code: str, latitude: Optional[float],
                  longitude: Optional[float], cache_weather: bool) -> np.ndarray:
    if (latitude is None) != (longitude is None):
        logger.warning("Set both LATITUDE and LONGITUDE; using the supply region centre.")
        latitude = longitude = None
    if latitude is None or longitude is None:
        centre = REGION_LATLON.get((region_code or "").upper())
        if centre is None:
            logger.warning(f"No coordinates for region {region_code}; training without weather.")
            return np.full((len(dates), SLOTS, 3), np.nan)
        latitude, longitude = centre
    try:
        hourly = _load_weather(latitude, longitude, dates[0], dates[-1], cache_weather)
    except Exception as exc:
        logger.warning(f"Weather fetch failed, training without it: {exc}")
        return np.full((len(dates), SLOTS, 3), np.nan)
    grid = np.full((len(dates), SLOTS, 3), np.nan)
    for day_index, day in enumerate(dates):
        for slot in range(SLOTS):
            grid[day_index, slot] = _slot_weather(hourly, day, slot)
    return grid


def _slot_weather(hourly: dict, day: date, slot: int) -> np.ndarray:
    hour = slot // 2
    minute = (slot % 2) * 30
    current = hourly.get((day, hour))
    if current is None:
        return np.array([np.nan, np.nan, np.nan])
    if minute == 0:
        return np.array(current, dtype=float)
    next_day, next_hour = (day, hour + 1) if hour < 23 else (day + timedelta(days=1), 0)
    nxt = hourly.get((next_day, next_hour))
    if nxt is None:
        return np.array(current, dtype=float)
    return (np.array(current, dtype=float) + np.array(nxt, dtype=float)) / 2


def _load_weather(latitude: float, longitude: float, start: date, end: date, use_cache: bool) -> dict:
    path = os.path.join(data_dir(), "demand_weather.json")
    cached = {}
    key = f"{latitude:.3f},{longitude:.3f}"
    if use_cache and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("key") == key:
                cached = payload.get("hours") or {}
        except (OSError, json.JSONDecodeError):
            cached = {}
    hourly = {}
    for stamp, values in cached.items():
        moment = datetime_from_stamp(stamp)
        hourly[(moment.date(), moment.hour)] = values
    refresh_from = end - timedelta(days=3)
    missing_archive = [
        day for day in _date_range(start, refresh_from - timedelta(days=1))
        if (day, 12) not in hourly
    ]
    if missing_archive:
        _merge_open_meteo(
            hourly,
            "https://archive-api.open-meteo.com/v1/archive",
            latitude, longitude, missing_archive[0], missing_archive[-1],
        )
    _merge_open_meteo(
        hourly,
        "https://api.open-meteo.com/v1/forecast",
        latitude, longitude, max(start, refresh_from), end,
        forecast=True,
    )
    if use_cache:
        serialised = {
            f"{day.isoformat()}T{hour:02d}": values
            for (day, hour), values in hourly.items()
        }
        temporary = f"{path}.tmp"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"key": key, "hours": serialised}, handle)
        os.replace(temporary, path)
    return hourly


def _merge_open_meteo(hourly: dict, url: str, latitude: float, longitude: float,
                      start: date, end: date, forecast: bool = False) -> None:
    import requests
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,relative_humidity_2m,shortwave_radiation",
        "timezone": "GMT",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    if forecast:
        params.pop("start_date")
        params.pop("end_date")
        params["past_days"] = min(7, (end - start).days + 2)
        params["forecast_days"] = 3
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json().get("hourly") or {}
    times = payload.get("time") or []
    temps = payload.get("temperature_2m") or []
    humidity = payload.get("relative_humidity_2m") or []
    solar = payload.get("shortwave_radiation") or []
    for stamp, temp, humid, sun in zip(times, temps, humidity, solar):
        moment = datetime_from_stamp(stamp)
        hourly[(moment.date(), moment.hour)] = [
            _finite(temp), _finite(sun), _finite(humid),
        ]


def _finite(value) -> float:
    if value is None:
        return float("nan")
    return float(value)


def datetime_from_stamp(stamp: str):
    from datetime import datetime
    text = stamp.replace("Z", "")
    if len(text) == 13:
        text = f"{text}:00"
    return datetime.fromisoformat(text)


def _date_range(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _attach_dates(cube: dict, dates: Sequence[date]) -> dict:
    cube["__dates"] = list(dates)
    return cube
