"""Summary statistics for a simulation result."""

from __future__ import annotations

import pandas as pd


def summarize(result: pd.DataFrame, cad_amount: float) -> dict:
    d = result["difference_usd"]
    return {
        "start_dates": int(len(result)),
        "first_start": result.index.min().date().isoformat(),
        "last_start": result.index.max().date().isoformat(),
        "mean_bank_usd": float(result["bank_usd"].mean()),
        "mean_gambit_usd": float(result["gambit_usd"].mean()),
        "mean_savings_usd": float(d.mean()),
        "std_savings_usd": float(d.std(ddof=1)) if len(d) > 1 else 0.0,
        "best_savings_usd": float(d.max()),
        "worst_savings_usd": float(d.min()),
        "best_start": d.idxmax().date().isoformat(),
        "worst_start": d.idxmin().date().isoformat(),
        "gambit_win_rate": float((d > 0).mean()),
        "mean_savings_pct": float((d / result["bank_usd"]).mean() * 100),
        "cad_amount": float(cad_amount),
    }


def format_summary(s: dict) -> str:
    return "\n".join(
        [
            f"Converting {s['cad_amount']:,.2f} CAD",
            f"Start dates tested: {s['start_dates']} ({s['first_start']} to {s['last_start']})",
            f"Average USD, bank:             {s['mean_bank_usd']:,.2f}",
            f"Average USD, Norbert's Gambit: {s['mean_gambit_usd']:,.2f}",
            f"Average savings: {s['mean_savings_usd']:,.2f} USD "
            f"({s['mean_savings_pct']:.2f}%), std dev {s['std_savings_usd']:,.2f}",
            f"Best case:  {s['best_savings_usd']:,.2f} USD (start {s['best_start']})",
            f"Worst case: {s['worst_savings_usd']:,.2f} USD (start {s['worst_start']})",
            f"Gambit beat the bank on {s['gambit_win_rate']:.1%} of start dates",
        ]
    )


def break_even_amount(df: pd.DataFrame, simulate_fn, assumptions, low=100.0, high=1_000_000.0) -> float | None:
    """Smallest CAD amount where the Gambit's average savings are positive.

    Uses bisection on the mean savings, which rises with the amount because the
    commissions are fixed while the spread saving scales with size.
    """
    def mean_saving(x: float) -> float:
        return simulate_fn(df, x, assumptions)["difference_usd"].mean()

    try:
        if mean_saving(high) <= 0:
            return None
        if mean_saving(low) > 0:
            return low
    except ValueError:
        return None
    for _ in range(60):
        mid = (low + high) / 2
        if mean_saving(mid) > 0:
            high = mid
        else:
            low = mid
    return round(high, 2)
