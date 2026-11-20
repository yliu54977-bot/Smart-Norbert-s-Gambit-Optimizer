"""The two conversion methods.

Bank:   USD = CAD x cadusd x (1 - bank_spread)

Norbert's Gambit, started on day t:
    1. Pay the buy commission in CAD and buy as many whole shares of the CAD
       listing as the rest allows, at the day-t close plus slippage.
    2. Leftover CAD that cannot buy a whole share goes through the bank.
    3. The shares are journaled to the USD listing over `delay_days` trading
       days. Dividends with an ex-date in (t, t + delay_days] are received in USD.
    4. Sell every share at the close of day t + delay_days minus slippage, and
       pay the sell commission in USD.

`delay_days = 0` models brokers that let you sell the USD side right away,
before the journal settles, which removes the price risk of waiting.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Assumptions:
    bank_spread: float = 0.02        # bank's FX markup, 0.02 = 2%
    commission: float = 9.95         # flat fee per trade (CAD to buy, USD to sell)
    per_share: float = 0.0           # extra fee per share per trade
    commission_min: float = 0.0      # floor on each trade's fee
    commission_max: float = float("inf")  # cap on each trade's fee
    delay_days: int = 4              # trading days to journal the shares
    slippage_bps: float = 5.0        # half bid-ask spread paid on each trade, in basis points

    def __post_init__(self) -> None:
        if not 0 <= self.bank_spread < 1:
            raise ValueError("bank_spread must be in [0, 1).")
        if min(self.commission, self.per_share, self.commission_min) < 0:
            raise ValueError("Commissions cannot be negative.")
        if self.commission_max < self.commission_min:
            raise ValueError("commission_max must be at least commission_min.")
        if self.delay_days < 0:
            raise ValueError("delay_days cannot be negative.")
        if not 0 <= self.slippage_bps < 1000:
            raise ValueError("slippage_bps must be between 0 and 1000.")

    def with_(self, **changes) -> "Assumptions":
        return replace(self, **changes)

    def trade_fee(self, shares: np.ndarray) -> np.ndarray:
        fee = self.commission + self.per_share * shares
        fee = np.clip(fee, self.commission_min, self.commission_max)
        return np.where(shares > 0, fee, 0.0)


def bank_usd(cad_amount, cadusd, spread: float):
    """USD received when the bank converts `cad_amount`."""
    return cad_amount * cadusd * (1 - spread)


def max_affordable_shares(cad_amount: float, price: np.ndarray, a: Assumptions) -> np.ndarray:
    """Largest whole number of shares whose cost plus buy fee fits in `cad_amount`.

    Cost plus fee rises with the share count, so a binary search over
    [0, amount / price] finds the answer for every start date at once.
    """
    lo = np.zeros_like(price)
    hi = np.floor(cad_amount / price)
    while (lo < hi).any():
        mid = np.ceil((lo + hi) / 2)
        fits = mid * price + a.trade_fee(mid) <= cad_amount + 1e-9
        lo = np.where(fits, mid, lo)
        hi = np.where(fits, hi, mid - 1)
    return lo


def simulate(df: pd.DataFrame, cad_amount: float, a: Assumptions = Assumptions()) -> pd.DataFrame:
    """Run both methods for every start date that has a sell date in the data.

    Returns one row per start date with the USD from each method and the
    difference (positive = Norbert's Gambit gave more USD).
    """
    if cad_amount <= 0:
        raise ValueError("cad_amount must be positive.")
    if len(df) <= a.delay_days:
        raise ValueError("Not enough trading days for the settlement delay.")

    d = a.delay_days
    n = len(df) - d
    cad_px = df["cad_price"].to_numpy()[:n]
    fx = df["cadusd"].to_numpy()[:n]
    sell_px = df["usd_price"].to_numpy()[d:]
    slip = a.slippage_bps / 10_000
    buy_px = cad_px * (1 + slip)

    divs = df["usd_dividend"].to_numpy() if "usd_dividend" in df else np.zeros(len(df))
    cum = np.concatenate([[0.0], np.cumsum(divs)])
    # dividends with ex-date in (t, t+d]: cum[t+d+1] - cum[t+1]
    div_per_share = cum[d + 1 : d + 1 + n] - cum[1 : 1 + n]

    shares = max_affordable_shares(cad_amount, buy_px, a)
    buy_fee = a.trade_fee(shares)
    leftover_cad = cad_amount - shares * buy_px - buy_fee
    if (leftover_cad < -1e-9).any():
        raise ValueError("cad_amount does not cover the buy commission.")
    if (shares == 0).all():
        raise ValueError("cad_amount is too small to buy one share.")

    proceeds = shares * (sell_px * (1 - slip) + div_per_share) - a.trade_fee(shares)
    gambit = proceeds + bank_usd(leftover_cad, fx, a.bank_spread)
    bank = bank_usd(cad_amount, fx, a.bank_spread)

    result = pd.DataFrame(
        {
            "sell_date": df.index[d:],
            "shares": shares.astype(int),
            "bank_usd": bank,
            "gambit_usd": gambit,
            "difference_usd": gambit - bank,
        },
        index=df.index[:n],
    )
    if "ok" in df:  # skip start dates whose holding window touches flagged data
        bad = (~df["ok"].to_numpy(bool)).astype(int)
        cum_bad = np.concatenate([[0], np.cumsum(bad)])
        window_ok = (cum_bad[d + 1 : d + 1 + n] - cum_bad[:n]) == 0
        result = result[window_ok]
        if result.empty:
            raise ValueError("No start dates with clean data.")
    return result
