"""The two conversion methods.

Bank:   USD = CAD x cadusd x (1 - spread)

Norbert's Gambit, started on day t:
    1. Pay a commission in CAD and buy as many whole shares of the CAD listing
       as the rest of the money allows, at the day-t close.
    2. Leftover CAD that cannot buy a whole share is converted at the bank rate.
    3. The shares are journaled to the US listing, which takes `delay_days`
       trading days.
    4. Sell all shares at the close of day t + delay_days and pay a USD
       commission.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Assumptions:
    bank_spread: float = 0.02      # 2% below the mid-market rate
    commission_cad: float = 9.95   # buy-side commission
    commission_usd: float = 9.95   # sell-side commission
    delay_days: int = 4            # trading days for the journal to settle

    def __post_init__(self) -> None:
        if not 0 <= self.bank_spread < 1:
            raise ValueError("bank_spread must be in [0, 1).")
        if self.commission_cad < 0 or self.commission_usd < 0:
            raise ValueError("Commissions cannot be negative.")
        if self.delay_days < 0:
            raise ValueError("delay_days cannot be negative.")


def bank_usd(cad_amount: float, cadusd: float | pd.Series, spread: float) -> float | pd.Series:
    """USD received when the bank converts `cad_amount`."""
    return cad_amount * cadusd * (1 - spread)


def simulate(df: pd.DataFrame, cad_amount: float, a: Assumptions = Assumptions()) -> pd.DataFrame:
    """Run both methods for every start date that has a sell date in the data.

    Returns one row per start date with the USD from each method and the
    difference (positive = Norbert's Gambit gave more USD).
    """
    if cad_amount <= 0:
        raise ValueError("cad_amount must be positive.")
    if len(df) <= a.delay_days:
        raise ValueError("Not enough trading days for the settlement delay.")

    n = len(df) - a.delay_days
    start = df.iloc[:n]
    sell_price = df["usd_price"].to_numpy()[a.delay_days:]
    sell_date = df.index[a.delay_days:]

    investable = cad_amount - a.commission_cad
    if investable <= 0:
        raise ValueError("cad_amount does not cover the buy commission.")

    shares = np.floor(investable / start["cad_price"].to_numpy())
    leftover_cad = investable - shares * start["cad_price"].to_numpy()
    leftover_usd = bank_usd(leftover_cad, start["cadusd"].to_numpy(), a.bank_spread)
    gambit = shares * sell_price - np.where(shares > 0, a.commission_usd, 0.0) + leftover_usd

    bank = bank_usd(cad_amount, start["cadusd"].to_numpy(), a.bank_spread)

    return pd.DataFrame(
        {
            "sell_date": sell_date,
            "shares": shares.astype(int),
            "bank_usd": bank,
            "gambit_usd": gambit,
            "difference_usd": gambit - bank,
        },
        index=start.index,
    )
