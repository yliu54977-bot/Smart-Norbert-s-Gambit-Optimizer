"""Charts for a simulation result."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def save_charts(result: pd.DataFrame, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(result.index, result["bank_usd"], label="Bank conversion", linewidth=1.4)
    ax.plot(result.index, result["gambit_usd"], label="Norbert's Gambit", linewidth=1.4)
    ax.set_title("USD received by start date")
    ax.set_ylabel("USD")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    paths.append(out / "usd_by_start_date.png")
    fig.savefig(paths[-1], dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(result["difference_usd"], bins=40, edgecolor="white")
    ax.axvline(0, color="black", linewidth=1)
    ax.axvline(result["difference_usd"].mean(), color="tab:red", linestyle="--", label="Mean")
    ax.set_title("Gambit minus bank (USD), all start dates")
    ax.set_xlabel("USD (positive = Gambit better)")
    ax.set_ylabel("Number of start dates")
    ax.legend()
    fig.tight_layout()
    paths.append(out / "savings_distribution.png")
    fig.savefig(paths[-1], dpi=150)
    plt.close(fig)

    return paths


def save_ranking_chart(table: pd.DataFrame, cad_amount: float, out_path: str | Path, top: int = 15) -> Path:
    """Horizontal chart of the top pairs: dot = average savings, line = 5th to
    95th percentile across start dates."""
    t = table.head(top).iloc[::-1]
    labels = [f"{c} → {u}" for c, u in zip(t["cad_ticker"], t["usd_ticker"])]
    y = range(len(t))
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(t) + 1.6))
    ax.hlines(y, t["p5_savings_usd"], t["p95_savings_usd"], color="tab:blue", alpha=0.45, linewidth=4,
              label="5th to 95th percentile")
    ax.plot(t["mean_savings_usd"], y, "o", color="tab:blue", label="Average")
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.set_xlabel("USD saved vs bank (negative = bank was better)")
    ax.set_title(f"Norbert's Gambit savings on {cad_amount:,.0f} CAD, ranked by 5th percentile")
    ax.grid(axis="x", alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def save_broker_chart(table: pd.DataFrame, cad_amount: float, out_path: str | Path) -> Path:
    """Cost of each broker's recommended method: bar = average, line = up to the
    95th percentile (the bad case)."""
    t = table.iloc[::-1]
    y = list(range(len(t)))
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(t) + 1.6))
    ax.barh(y, t["mean_cost_usd"], color="tab:blue", alpha=0.8, label="Average cost")
    ax.hlines(y, t["mean_cost_usd"], t["p95_cost_usd"], color="black", linewidth=1.5, label="Up to bad case (95th pct)")
    for yi, (p95, label) in enumerate(zip(t["p95_cost_usd"], t["recommended"])):
        ax.text(p95 + t["p95_cost_usd"].max() * 0.02, yi, label, va="center", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels(t["broker"])
    ax.set_xlabel("USD lost vs the mid-market rate (lower is better)")
    ax.set_title(f"Cost to convert {cad_amount:,.0f} CAD to USD, cheapest method at each broker")
    ax.set_xlim(0, t["p95_cost_usd"].max() * 1.6)
    ax.grid(axis="x", alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
