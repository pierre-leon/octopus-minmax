import logging
import os
from datetime import datetime, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from comparison_engine import ComparisonResult

logger = logging.getLogger("octobot.chart")

_LONDON = ZoneInfo("Europe/London")
_INK = "#121212"
_GRID = "#2c2c2c"
_STANDING = "#146B45"
_CONSUMPTION = "#3DDC97"
_ON_CONSUMPTION = "#10241c"
_AGILE = "#F0C14A"
_COSY = "#FF7A59"
_TODAY_HIGHER = "#FF4DCD"
_FORECAST_HIGHER = "#6CB6FF"

STANDING_COLOR = _STANDING
CONSUMPTION_COLOR = _CONSUMPTION


def _chart_directory() -> str:
    for directory in ("/data", "/app/logs", "/tmp"):
        if os.path.isdir(directory) and os.access(directory, os.W_OK):
            return directory
    return "/tmp"


def _chart_path() -> str:
    return os.path.join(_chart_directory(), "tariff_comparison.jpg")


def _forecast_path() -> str:
    return os.path.join(_chart_directory(), "forecast_tomorrow.jpg")


def _pounds(value: float) -> str:
    return f"£{value:.2f}"


def _label(ax, x: float, y: float, text: str, va: str = "center", ha: str = "center",
          color: str = "white") -> None:
    ax.text(x, y, text, ha=ha, va=va, color=color, fontsize=9, clip_on=True)


def _draw_cost_bars(
    ax,
    labels: Sequence[str],
    standing_charges: Sequence[float],
    consumption_costs: Sequence[float],
    total_costs: Sequence[float],
) -> None:
    xs = list(range(len(labels)))
    has_negative_total = any(total < 0 for total in total_costs)

    standing_bars = ax.bar(xs, standing_charges, color=STANDING_COLOR, zorder=2)

    positive_consumption = [cost if cost > 0 else 0 for cost in consumption_costs]
    ax.bar(xs, positive_consumption, bottom=standing_charges, color=CONSUMPTION_COLOR, zorder=3)

    hatch_heights = []
    hatch_bottoms = []
    below_zero = []
    for standing, consumption, total in zip(standing_charges, consumption_costs, total_costs):
        if consumption >= 0:
            hatch_heights.append(0)
            hatch_bottoms.append(0)
            below_zero.append(0)
            continue
        # Hatch the standing charge from the net remainder (or 0) up to the full S/C.
        hatch_bottom = max(total, 0)
        hatch_heights.append(max(standing - hatch_bottom, 0))
        hatch_bottoms.append(hatch_bottom)
        below_zero.append(total if total < 0 else 0)

    ax.bar(
        xs,
        hatch_heights,
        bottom=hatch_bottoms,
        facecolor=CONSUMPTION_COLOR,
        edgecolor="white",
        hatch="///",
        linewidth=0.6,
        zorder=4,
    )
    ax.bar(xs, below_zero, color=CONSUMPTION_COLOR, zorder=3)

    visual_tops = [standing + max(consumption, 0) for standing, consumption in zip(standing_charges, consumption_costs)]
    visual_bottoms = [min(0, total) for total in total_costs]
    y_max = max(visual_tops) if visual_tops else 1
    y_min = min(visual_bottoms) if visual_bottoms else 0
    headroom = max(abs(y_max) * 0.22, abs(y_min) * 0.35, 0.18)
    ax.set_ylim(y_min - (headroom if y_min < 0 else 0), y_max + headroom)
    span = ax.get_ylim()[1] - ax.get_ylim()[0]
    min_inside = span * 0.08
    total_offset = span * 0.04

    if has_negative_total or any(cost < 0 for cost in consumption_costs):
        ax.axhline(0, color="white", linewidth=0.8, zorder=1)

    for x, bar, standing, consumption, total, hatch_h, hatch_b in zip(
        xs, standing_bars, standing_charges, consumption_costs, total_costs, hatch_heights, hatch_bottoms
    ):
        cx = bar.get_x() + bar.get_width() / 2
        if consumption >= 0:
            if standing >= min_inside:
                _label(ax, cx, standing / 2, _pounds(standing))
            if consumption >= min_inside:
                _label(ax, cx, standing + consumption / 2, _pounds(consumption), color=_ON_CONSUMPTION)
            _label(ax, cx, total + total_offset, _pounds(total), va="bottom")
            continue

        remainder = hatch_b  # unhatched S/C when total > 0, else 0
        if remainder >= min_inside:
            _label(ax, cx, remainder / 2, _pounds(standing))
        elif standing >= min_inside:
            _label(ax, cx, standing / 2, _pounds(standing))

        if total < 0:
            if abs(total) >= min_inside:
                _label(ax, cx, total / 2, _pounds(consumption), color=_ON_CONSUMPTION)
            elif hatch_h >= min_inside:
                _label(ax, cx, hatch_b + hatch_h / 2, _pounds(consumption), color=_ON_CONSUMPTION)
            else:
                _label(ax, cx + 0.42, (total / 2) if total else standing / 2, _pounds(consumption), ha="left")
            _label(ax, cx, total - total_offset, _pounds(total), va="top")
        else:
            if hatch_h >= min_inside:
                _label(ax, cx, hatch_b + hatch_h / 2, _pounds(consumption), color=_ON_CONSUMPTION)
            elif hatch_h > 0:
                _label(ax, cx + 0.42, hatch_b + hatch_h / 2, _pounds(consumption), ha="left", color=_ON_CONSUMPTION)
            _label(ax, cx, standing + total_offset, _pounds(total), va="bottom")

    ax.set_ylabel("Cost (£)", color="white")
    ax.set_xticks(xs)
    ax.set_xticklabels(list(labels), rotation=45, ha="right", color="white")
    ax.tick_params(colors="white")
    ax.grid(True, axis="y", color=_GRID, linewidth=0.6)
    ax.grid(False, axis="x")
    for spine in ax.spines.values():
        spine.set_color(_GRID)


def create_tariff_comparison_chart(result: ComparisonResult) -> Optional[str]:
    """Render a stacked bar chart of standing charge vs consumption cost per tariff."""
    valid = [comparison for comparison in result.all_comparisons if comparison.is_valid]
    if not valid:
        logger.warning("No valid tariff comparisons available to chart")
        return None

    labels = [comparison.tariff.display_name for comparison in valid]
    standing_charges = [comparison.cost_breakdown.standing_charge_pounds for comparison in valid]
    consumption_costs = [comparison.cost_breakdown.consumption_cost_pounds for comparison in valid]
    total_costs = [comparison.cost_breakdown.total_cost_pounds for comparison in valid]

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 6))
    fig.patch.set_facecolor(_INK)
    ax.set_facecolor(_INK)
    _draw_cost_bars(ax, labels, standing_charges, consumption_costs, total_costs)
    plt.tight_layout()

    path = _chart_path()
    try:
        fig.savefig(path, format="jpeg", dpi=120, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    except ValueError:
        path = os.path.splitext(path)[0] + ".png"
        fig.savefig(path, format="png", dpi=120, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)

    size = os.path.getsize(path) if os.path.isfile(path) else 0
    if size <= 0:
        logger.error(f"Comparison chart was not written to {path}")
        return None

    logger.info(f"Wrote comparison chart ({size} bytes) to {path}")
    return path


def _local_label(stamp: str) -> str:
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(_LONDON)
    return moment.strftime("%H:%M")


def _line(values: Sequence[Optional[float]]) -> np.ndarray:
    return np.array([np.nan if value is None else value for value in values], dtype=float)


def _fit_forecast_axes(ax, use) -> None:
    """Keep the price axis open below zero, with both scales sharing that line."""
    finite = [float(value) for line in ax.get_lines() for value in line.get_ydata() if np.isfinite(value)]
    low = min(finite) if finite else 0.0
    price_low, price_top = ax.get_ylim()
    _, kwh_top = use.get_ylim()
    if low >= 0:
        ax.set_ylim(0, max(price_top, 0))
        use.set_ylim(bottom=0)
        return
    price_top = max(price_top, 1.0)
    price_low = min(price_low, low - max(price_top - low, 1.0) * 0.05)
    kwh_top = max(kwh_top, 1e-3)
    use.set_ylim(-kwh_top * abs(price_low) / price_top, kwh_top)
    kept = [tick for tick in use.get_yticks() if tick >= -1e-9]
    if kept:
        use.set_yticks(kept)
    ax.set_ylim(price_low, price_top)
    ax.axhline(0, color="white", linewidth=0.8, zorder=2)


def _price_line(ax, xs, values, color: str, label: str) -> None:
    """A white edge under the rate so it stays visible across the bars."""
    series = _line(values)
    ax.plot(xs, series, color="white", linewidth=5.0, drawstyle="steps-mid",
            solid_capstyle="round", zorder=3)
    ax.plot(xs, series, color=color, linewidth=2.6, drawstyle="steps-mid",
            solid_capstyle="round", label=label, zorder=4)


def _clock(raw: str) -> str:
    text = raw.strip().replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    minute = 0 if moment.minute < 30 else 30
    return f"{moment.hour:02d}:{minute:02d}"


def align_actuals(stamps: Sequence[str], entries: Sequence[dict]) -> list:
    """Today's kWh on the same UTC clock as each forecast stamp."""
    totals = {}
    for entry in entries:
        raw = entry.get("readAt")
        if not raw or entry.get("consumptionDelta") is None:
            continue
        clock = _clock(raw)
        totals[clock] = totals.get(clock, 0.0) + float(entry["consumptionDelta"]) / 1000
    return [totals.get(_clock(stamp)) for stamp in stamps]


def bar_layers(predicted: Sequence[float], actual: Optional[Sequence[Optional[float]]]):
    """Overlap in the first list, today's extra in the second, the forecast's extra in the third."""
    actuals = list(actual) if actual is not None else [None] * len(predicted)
    shared, today_higher, forecast_higher = [], [], []
    for pred, act in zip(predicted, actuals):
        pred = max(float(pred), 0.0)
        if act is None:
            shared.append(pred)
            today_higher.append(0.0)
            forecast_higher.append(0.0)
            continue
        act = max(float(act), 0.0)
        shared.append(min(pred, act))
        if act > pred:
            today_higher.append(act - pred)
            forecast_higher.append(0.0)
        else:
            today_higher.append(0.0)
            forecast_higher.append(pred - act)
    return shared, today_higher, forecast_higher


def create_forecast_chart(stamps: Sequence[str], consumption_kwh: Sequence[float],
                          agile_pence: Sequence[Optional[float]],
                          cosy_pence: Sequence[Optional[float]],
                          path: Optional[str] = None,
                          actual_kwh: Optional[Sequence[Optional[float]]] = None) -> Optional[str]:
    """Bars for every predicted half-hour. A missing rate stops that line."""
    count = len(stamps)
    if count == 0 or len(consumption_kwh) != count:
        logger.warning("Forecast chart needs one consumption value per half-hour")
        return None

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(11.5, 4.4))
    fig.patch.set_facecolor(_INK)
    ax.set_facecolor(_INK)
    use = ax.twinx()
    xs = np.arange(count)
    if actual_kwh is not None and len(actual_kwh) != count:
        actual_kwh = None
    shared, today_higher, forecast_higher = bar_layers(consumption_kwh, actual_kwh)
    use.bar(xs, shared, color=_CONSUMPTION, width=0.84, zorder=1)
    use.bar(xs, forecast_higher, bottom=shared, color=_FORECAST_HIGHER, width=0.84, zorder=1)
    today_bottom = [left + extra for left, extra in zip(shared, forecast_higher)]
    use.bar(xs, today_higher, bottom=today_bottom, color=_TODAY_HIGHER, width=0.84, zorder=1)
    ax.set_zorder(use.get_zorder() + 1)
    ax.patch.set_visible(False)

    if any(value is not None for value in agile_pence):
        _price_line(ax, xs, agile_pence, _AGILE, "Agile")
    if any(value is not None for value in cosy_pence):
        _price_line(ax, xs, cosy_pence, _COSY, "Cosy")

    ax.set_ylabel("p/kWh", color="white")
    use.set_ylabel("kWh", color="white")
    _fit_forecast_axes(ax, use)
    ax.set_xlim(-0.6, count - 0.4)
    labels = [_local_label(stamp) if index % 4 == 0 else "" for index, stamp in enumerate(stamps)]
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, color="white", fontsize=8)
    ax.tick_params(colors="white")
    use.tick_params(colors="white")
    ax.grid(True, axis="y", color=_GRID, linewidth=0.6)
    ax.grid(False, axis="x")
    for spine in list(ax.spines.values()) + list(use.spines.values()):
        spine.set_color(_GRID)
    handles, labels = ax.get_legend_handles_labels()
    if actual_kwh is not None:
        handles = [Patch(facecolor=_CONSUMPTION, label="Forecast")] + handles
        labels = ["Forecast"] + labels
        if any(value > 0 for value in today_higher):
            handles.append(Patch(facecolor=_TODAY_HIGHER, label="Today higher"))
            labels.append("Today higher")
        if any(value > 0 for value in forecast_higher):
            handles.append(Patch(facecolor=_FORECAST_HIGHER, label="Forecast higher"))
            labels.append("Forecast higher")
    if handles:
        legend = ax.legend(handles, labels, loc="upper left", frameon=False, fontsize=8)
        for text in legend.get_texts():
            text.set_color("white")
    plt.tight_layout()

    path = path or _forecast_path()
    try:
        fig.savefig(path, format="jpeg", dpi=130, facecolor=fig.get_facecolor(),
                    bbox_inches="tight", pad_inches=0.15)
    except ValueError:
        path = os.path.splitext(path)[0] + ".png"
        fig.savefig(path, format="png", dpi=130, facecolor=fig.get_facecolor(),
                    bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)

    size = os.path.getsize(path) if os.path.isfile(path) else 0
    if size <= 0:
        logger.error(f"Forecast chart was not written to {path}")
        return None
    logger.info(f"Wrote forecast chart ({size} bytes) to {path}")
    return path
