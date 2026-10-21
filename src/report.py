"""The nightly message: today's bills, tomorrow's Agile/Cosy prices, one decision."""

from typing import Optional, Sequence

from comparison_engine import ComparisonResult, TariffComparison


_SHORT = {
    "agile": "Agile",
    "cosy": "Cosy",
    "go": "Go",
    "flexible": "Flex",
    "go-fix-12m": "Go 12M",
}


def short_name(tariff_id: str, display_name: str = "") -> str:
    return _SHORT.get(tariff_id, display_name or tariff_id)


def profile_kwh(profile: Sequence[dict]) -> float:
    return sum(float(row.get("consumptionDelta") or 0) for row in profile) / 1000


def with_version(stated_on, today, version: str, message: str):
    """Version sits on the first report of the day. Returns the text and the day it was stated."""
    if stated_on == today:
        return message, stated_on
    return f"{version}\n\n{message}", today


def early_report_needed(prediction_error: Optional[str], method: Optional[str],
                        comparisons_ok: bool, switching: bool) -> bool:
    """A clean stay stays quiet. Failures, a fallback forecast, and a real switch do not."""
    if prediction_error or not comparisons_ok or switching:
        return True
    return method not in (None, "ensemble")


def _unit_pence(comparison: TariffComparison) -> Optional[float]:
    breakdown = comparison.cost_breakdown
    if breakdown is None or breakdown.total_kwh <= 0:
        return None
    return breakdown.consumption_cost / breakdown.total_kwh


def _money_row(comparison: TariffComparison, bold: bool, standing: bool) -> str:
    name = short_name(comparison.tariff.id, comparison.tariff.display_name)
    if not comparison.is_valid or comparison.cost_breakdown is None:
        return f"{name}: {comparison.error or 'no price'}"
    label = f"{name} £{comparison.cost_breakdown.total_cost_pounds:.2f}"
    if bold:
        label = f"*{label}*"
    pence = _unit_pence(comparison)
    row = f"{label} | {pence:.1f}p" if pence is not None else label
    if standing:
        row += f" | sc {comparison.cost_breakdown.standing_charge:.0f}p"
    return row


def _bold_ids(comparisons: Sequence[TariffComparison]) -> set:
    costs = [item.total_cost for item in comparisons if item.is_valid and item.total_cost is not None]
    if not costs:
        return set()
    cheapest = min(costs)
    return {item.tariff.id for item in comparisons if item.is_valid and item.total_cost == cheapest}


def format_today(result: ComparisonResult) -> str:
    rows = [result.current_tariff_comparison] + list(result.alternative_comparisons)
    bold = _bold_ids(rows)
    kwh = None
    for comparison in rows:
        if comparison.cost_breakdown is not None:
            kwh = comparison.cost_breakdown.total_kwh
            break
    lines = [f"*Today {kwh:.2f} kWh*" if kwh is not None else "*Today*"]
    lines.extend(_money_row(comparison, comparison.tariff.id in bold, standing=False) for comparison in rows)
    return "\n".join(lines)


def format_tomorrow(prediction: Optional[dict], error: Optional[str]) -> str:
    if error or not prediction:
        return f"*Tomorrow*\nNo forecast. {error or ''}".strip()
    profile = prediction.get("profile") or []
    kwh = profile_kwh(profile) if profile else None
    lines = [f"*Tomorrow {kwh:.2f}kWh*" if kwh is not None else "*Tomorrow*"]
    priced = [prediction[key] for key in ("agile", "cosy") if prediction.get(key) is not None]
    bold = _bold_ids(priced)
    lines.extend(
        _money_row(comparison, comparison.tariff.id in bold, standing=True)
        for comparison in priced
    )
    if prediction.get("method") != "ensemble":
        detail = prediction.get("detail") or ""
        lines.append(f"Forecast fell back to the slot average. {detail}".strip())
    return "\n".join(lines)


def hop_decision_line(current_id: str, today_cosy_cheaper: bool, tomorrow_saving: Optional[float],
                      tomorrow_agile_cheaper: bool, target_names: Sequence[str], phase: str,
                      execution_time: str) -> str:
    if current_id == "agile" and not today_cosy_cheaper:
        if tomorrow_agile_cheaper or tomorrow_saving is None:
            return "Staying on Agile."
        return "Staying on Agile. Tomorrow's Cosy switch waits until that day is metered."
    if not target_names:
        return f"Staying on {short_name(current_id)}."
    names = " then ".join(target_names)
    if phase == "early":
        return f"Switching to {names} at {execution_time}."
    return f"Switching to {names}."


def format_report(result: ComparisonResult, prediction: Optional[dict], error: Optional[str],
                  decision: str, tomorrow: bool = True) -> str:
    parts = [format_today(result)]
    if tomorrow:
        parts.extend(["", format_tomorrow(prediction, error)])
    if decision:
        parts.append(decision)
    return "\n".join(parts)
