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
