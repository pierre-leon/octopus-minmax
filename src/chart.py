import logging
import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from comparison_engine import ComparisonResult

logger = logging.getLogger("octobot.chart")


def _chart_path() -> str:
    for directory in ("/data", "/app/logs", "/tmp"):
        if os.path.isdir(directory) and os.access(directory, os.W_OK):
            return os.path.join(directory, "tariff_comparison.jpg")
    return "/tmp/tariff_comparison.jpg"


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
    fig.patch.set_facecolor("#121212")
    ax.set_facecolor("#121212")
    bars_standing = ax.bar(labels, standing_charges, color="#9A3B3B")
    ax.bar(labels, consumption_costs, bottom=standing_charges, color="#632626")

    for bar, standing, consumption in zip(bars_standing, standing_charges, consumption_costs):
        ax.text(bar.get_x() + bar.get_width() / 2, standing / 2, f"£{standing:.2f}", ha="center", color="white")
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            standing + consumption / 2,
            f"£{consumption:.2f}",
            ha="center",
            color="white",
        )

    for bar, total in zip(bars_standing, total_costs):
        ax.text(bar.get_x() + bar.get_width() / 2, total + 0.05, f"£{total:.2f}", ha="center", color="white")

    ax.set_ylabel("Cost (£)", color="white")
    plt.xticks(rotation=45, ha="right", color="white")
    plt.yticks(color="white")
    ax.grid(False, axis="x")
    plt.tight_layout()

    path = _chart_path()
    try:
        fig.savefig(path, format="jpeg", dpi=120, facecolor=fig.get_facecolor(), bbox_inches="tight")
    except ValueError:
        path = os.path.splitext(path)[0] + ".png"
        fig.savefig(path, format="png", dpi=120, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)

    size = os.path.getsize(path) if os.path.isfile(path) else 0
    if size <= 0:
        logger.error(f"Comparison chart was not written to {path}")
        return None

    logger.info(f"Wrote comparison chart ({size} bytes) to {path}")
    return path
