"""Test every security in the universe and find the best way to convert.

Two questions matter to someone converting money:

* How much do I save on average?  -> `mean_savings_usd`
* How bad can it go?              -> `p5_savings_usd`: in 95% of the start
  dates tested the result was at least this good.

The recommended method is the one with the best 5th percentile: the most USD
you could almost count on. The bank is recommended when no pair beats it even
on average.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .data import clean_pair, pair_frame
from .models import Assumptions, simulate
from .stats import break_even_amount, summarize
from .universe import Pair

MIN_DAYS = 250  # need about a year of data for a pair to be ranked


def build_frames(wide: pd.DataFrame, pairs: list[Pair], max_gap: float = 0.03) -> dict[str, dict]:
    """Pair frames for every pair that has enough clean data."""
    frames = {}
    for p in pairs:
        try:
            df, derived = pair_frame(wide, p)
        except (KeyError, ValueError) as exc:
            warnings.warn(f"Skipping {p.cad}/{p.usd}: {exc}")
            continue
        df, dropped = clean_pair(df, max_gap)
        if int(df["ok"].sum()) < MIN_DAYS:
            warnings.warn(f"Skipping {p.cad}/{p.usd}: only {int(df['ok'].sum())} clean days.")
            continue
        frames[p.cad] = {"pair": p, "df": df, "derived": derived, "dropped": dropped}
    return frames


def rank_pairs(
    frames: dict[str, dict],
    cad_amount: float,
    a: Assumptions = Assumptions(),
    with_break_even: bool = True,
) -> pd.DataFrame:
    """One row per pair, best (highest 5th-percentile savings) first."""
    rows = []
    for item in frames.values():
        p, df = item["pair"], item["df"]
        try:
            s = summarize(simulate(df, cad_amount, a), cad_amount)
        except ValueError:
            continue  # amount too small to buy one share of this security
        rows.append(
            {
                "name": p.name,
                "cad_ticker": p.cad,
                "usd_ticker": p.usd,
                "kind": p.kind,
                "start_dates": s["start_dates"],
                "mean_savings_usd": s["mean_savings_usd"],
                "median_savings_usd": s["median_savings_usd"],
                "std_savings_usd": s["std_savings_usd"],
                "p5_savings_usd": s["p5_savings_usd"],
                "p95_savings_usd": s["p95_savings_usd"],
                "worst_savings_usd": s["worst_savings_usd"],
                "win_rate": s["gambit_win_rate"],
                "mean_savings_pct": s["mean_savings_pct"],
                "break_even_cad": break_even_amount(df, simulate, a) if with_break_even else np.nan,
                "usd_price_derived": item["derived"],
                "days_flagged": item["dropped"],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["p5_savings_usd", "mean_savings_usd"], ascending=False).reset_index(drop=True)


def recommend(table: pd.DataFrame) -> dict:
    """Pick the method to use from a ranking table.

    Norbert's Gambit is recommended only with a pair that beat the bank in at
    least 95% of start dates (5th percentile above zero); among those, the one
    with the best 5th percentile. Otherwise the bank is the safer choice.
    """
    if table.empty:
        return {"method": "Bank", "reason": "No pair could be tested at this amount."}
    best_avg = table.sort_values("mean_savings_usd", ascending=False).iloc[0]
    highest_average = (f"{best_avg['cad_ticker']} ({best_avg['mean_savings_usd']:,.2f} USD avg, "
                       f"5th percentile {best_avg['p5_savings_usd']:,.2f})")
    safest = table.iloc[0]
    if safest["p5_savings_usd"] <= 0:
        return {
            "method": "Bank",
            "reason": f"No pair beat the bank in 95% of start dates. Safest pair: {safest['cad_ticker']} "
            f"({safest['mean_savings_usd']:,.2f} USD avg, 5th percentile {safest['p5_savings_usd']:,.2f}).",
            "highest_average": highest_average,
        }
    return {
        "method": f"Norbert's Gambit with {safest['cad_ticker']} -> {safest['usd_ticker']}",
        "name": safest["name"],
        "mean_savings_usd": float(safest["mean_savings_usd"]),
        "p5_savings_usd": float(safest["p5_savings_usd"]),
        "win_rate": float(safest["win_rate"]),
        "highest_average": highest_average,
    }


def best_by_amount(frames: dict[str, dict], amounts: list[float], a: Assumptions = Assumptions()) -> pd.DataFrame:
    """For each amount, the recommended method and how it compares with the bank."""
    rows = []
    for amt in amounts:
        table = rank_pairs(frames, amt, a, with_break_even=False)
        rec = recommend(table)
        rows.append(
            {
                "cad_amount": amt,
                "recommended": rec["method"],
                "mean_savings_usd": rec.get("mean_savings_usd", 0.0),
                "p5_savings_usd": rec.get("p5_savings_usd", 0.0),
                "win_rate": rec.get("win_rate", np.nan),
            }
        )
    return pd.DataFrame(rows)


def sensitivity(df: pd.DataFrame, cad_amount: float, a: Assumptions, field: str, values: list) -> pd.DataFrame:
    """How one pair's results change as one assumption changes."""
    rows = []
    for v in values:
        s = summarize(simulate(df, cad_amount, a.with_(**{field: v})), cad_amount)
        rows.append({field: v, "mean_savings_usd": s["mean_savings_usd"],
                     "p5_savings_usd": s["p5_savings_usd"], "win_rate": s["gambit_win_rate"]})
    return pd.DataFrame(rows)
