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

from .data import clean_pair, pair_frame, with_tsx_close_fx
from .models import Assumptions, simulate
from .stats import break_even_amount, summarize
from .brokers import Broker
from .universe import Pair

MIN_DAYS = 250  # need about a year of data for a pair to be ranked


def build_frames(
    wide: pd.DataFrame, pairs: list[Pair], max_gap: float = 0.03, fx_source: str = "dlr"
) -> dict[str, dict]:
    """Pair frames for every pair that has enough clean data.

    fx_source "dlr" (default) uses the 4 pm exchange rate measured from DLR
    (see data.fx_at_tsx_close); "yahoo" uses Yahoo's CADUSD=X close as is.
    """
    if fx_source == "dlr":
        wide = with_tsx_close_fx(wide)
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
    broker: Broker | None = None,
) -> pd.DataFrame:
    """One row per pair, best (highest 5th-percentile savings) first.

    With a broker, only the pairs it allows are tested, each with the broker's
    waiting time for that kind of security (e.g. RBC lets you sell DLR.U at once).
    """
    rows = []
    for item in frames.values():
        p, df = item["pair"], item["df"]
        pa = a
        if broker is not None:
            if not broker.allows(p.cad):
                continue
            pa = a.with_(delay_days=broker.delay_for(p.cad))
        try:
            result = simulate(df, cad_amount, pa)
        except ValueError:
            continue  # amount too small to buy one share of this security
        s = summarize(result, cad_amount)
        cost = result["mid_usd"] - result["gambit_usd"]
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
                "mean_cost_usd": float(cost.mean()),
                "p95_cost_usd": float(np.percentile(cost, 95)),
                "delay_days": pa.delay_days,
                "break_even_cad": break_even_amount(df, simulate, pa) if with_break_even else np.nan,
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


def best_by_amount(
    frames: dict[str, dict], amounts: list[float], a: Assumptions = Assumptions(), broker: Broker | None = None
) -> pd.DataFrame:
    """For each amount, the recommended method and how it compares with the bank."""
    rows = []
    for amt in amounts:
        aa = a if broker is None else a.with_(bank_spread=broker.fx_spread(amt, mean_fx(frames)))
        table = rank_pairs(frames, amt, aa, with_break_even=False, broker=broker)
        rec = recommend(table)
        method = rec["method"]
        if broker is not None and method == "Bank":
            method = "Convert directly"
        rows.append(
            {
                "cad_amount": amt,
                "recommended": method,
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


def mean_fx(frames: dict[str, dict]) -> float:
    """Average CADUSD over the data, used to place an amount in a broker's FX tier."""
    for item in frames.values():
        return float(item["df"]["cadusd"].mean())
    return 0.73


def broker_assumptions(broker: Broker, cad_amount: float, fx: float, base: Assumptions = Assumptions()) -> Assumptions:
    """The base assumptions with this broker's fees, conversion spread and journal fee."""
    return base.with_(
        bank_spread=broker.fx_spread(cad_amount, fx),
        commission=broker.commission,
        per_share=broker.per_share,
        commission_min=broker.commission_min,
        commission_max=broker.commission_max,
        journal_fee=broker.journal_fee,
    )


def compare_brokers(
    frames: dict[str, dict], brokers: list[Broker], cad_amount: float, base: Assumptions = Assumptions()
) -> pd.DataFrame:
    """Cost of the safest worthwhile method at each broker, lowest average cost first.

    Costs are in USD against the mid-market rate: how many fewer US dollars you
    get than a perfect, free conversion would give. `p95_cost_usd` is the bad
    case: in 95% of start dates the cost was at most this much.
    """
    fx = mean_fx(frames)
    rows = []
    for b in brokers:
        a = broker_assumptions(b, cad_amount, fx, base)
        direct_cost = cad_amount * fx * a.bank_spread
        row = {
            "broker": b.name,
            "key": b.key,
            "direct_fx_spread": a.bank_spread,
            "direct_cost_usd": direct_cost,
            "gambit_pair": "",
            "gambit_mean_cost_usd": np.nan,
            "gambit_p95_cost_usd": np.nan,
            "recommended": "Convert directly",
            "mean_cost_usd": direct_cost,
            "p95_cost_usd": direct_cost,
            "fx_tiers_complete": b.fx_tiers_complete,
            "source_quality": b.source_quality,
        }
        if b.gambit != "not_needed":
            table = rank_pairs(frames, cad_amount, a, with_break_even=False, broker=b)
            if not table.empty:
                best = table.iloc[0]
                row.update(
                    gambit_pair=f"{best['cad_ticker']} -> {best['usd_ticker']}",
                    gambit_mean_cost_usd=best["mean_cost_usd"],
                    gambit_p95_cost_usd=best["p95_cost_usd"],
                )
                if best["p5_savings_usd"] > 0:  # beat direct conversion in 95% of start dates
                    row.update(
                        recommended=f"Norbert's Gambit ({best['cad_ticker']})",
                        mean_cost_usd=best["mean_cost_usd"],
                        p95_cost_usd=best["p95_cost_usd"],
                    )
        rows.append(row)
    out = pd.DataFrame(rows)
    return out.sort_values(["mean_cost_usd", "p95_cost_usd"]).reset_index(drop=True)
