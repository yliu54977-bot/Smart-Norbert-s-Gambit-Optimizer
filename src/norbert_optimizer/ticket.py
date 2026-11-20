"""One Gambit, step by step: a trade ticket.

Use it to paper-test a conversion before doing it for real, or to check a
real conversion afterwards: give the prices you got (or want to test) and the
ticket shows every step, the USD you end up with, and how that compares with
the mid-market rate and with the broker's direct conversion. With
`actual_usd`, it also shows how far the real result was from the ticket.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .models import Assumptions, max_affordable_shares


@dataclass
class Ticket:
    cad_amount: float
    cad_price: float          # price paid per CAD-listed share (the ask)
    usd_price: float          # price received per USD-listed share (the bid)
    fx_mid: float             # mid-market USD per CAD when you start
    journal_fee_cad: float
    shares: int
    buy_fee_cad: float
    leftover_cad: float
    sell_fee_usd: float
    dividends_usd: float
    leftover_usd: float
    gambit_usd: float
    direct_usd: float
    mid_usd: float
    cost_vs_mid_usd: float
    saving_vs_direct_usd: float
    effective_rate: float     # USD received per CAD
    actual_usd: float | None = None
    model_error_usd: float | None = None

    def lines(self) -> list[str]:
        out = [
            f"Start with {self.cad_amount:,.2f} CAD",
            f"  Journal fee set aside:         -{self.journal_fee_cad:,.2f} CAD",
            f"  Buy {self.shares:,} shares at {self.cad_price:.4f} CAD:  -{self.shares * self.cad_price:,.2f} CAD",
            f"  Buy commission:                -{self.buy_fee_cad:,.2f} CAD",
            f"  Leftover {self.leftover_cad:,.2f} CAD converted directly: +{self.leftover_usd:,.2f} USD",
            f"Journal the shares, then",
            f"  Sell {self.shares:,} shares at {self.usd_price:.4f} USD: +{self.shares * self.usd_price:,.2f} USD",
        ]
        if self.dividends_usd:
            out.append(f"  Dividends received:            +{self.dividends_usd:,.2f} USD")
        out += [
            f"  Sell commission:               -{self.sell_fee_usd:,.2f} USD",
            f"You get {self.gambit_usd:,.2f} USD (effective rate {self.effective_rate:.5f} USD per CAD)",
            f"  Mid-market value:   {self.mid_usd:,.2f} USD -> cost {self.cost_vs_mid_usd:,.2f} USD",
            f"  Direct conversion:  {self.direct_usd:,.2f} USD -> Gambit saves {self.saving_vs_direct_usd:,.2f} USD",
        ]
        if self.actual_usd is not None:
            out.append(f"  Actually received:  {self.actual_usd:,.2f} USD -> "
                       f"{self.model_error_usd:+,.2f} USD vs this ticket")
        return out


def make_ticket(
    cad_amount: float,
    cad_price: float,
    usd_price: float,
    fx_mid: float,
    a: Assumptions,
    dividends_per_share: float = 0.0,
    actual_usd: float | None = None,
) -> Ticket:
    """Ticket for one Gambit at the given prices.

    `cad_price` and `usd_price` are taken as the prices you trade at, so no
    slippage is added: pass the ask you buy at and the bid you sell at.
    """
    budget = cad_amount - a.journal_fee
    if budget <= 0:
        raise ValueError("cad_amount does not cover the journal fee.")
    shares = int(max_affordable_shares(budget, np.array([cad_price]), a)[0])
    if shares == 0:
        raise ValueError("cad_amount is too small to buy one share.")
    buy_fee = float(a.trade_fee(np.array([shares]))[0])
    leftover_cad = budget - shares * cad_price - buy_fee
    leftover_usd = leftover_cad * fx_mid * (1 - a.bank_spread)
    sell_fee = float(a.trade_fee(np.array([shares]))[0])
    dividends = shares * dividends_per_share
    gambit = shares * usd_price + dividends - sell_fee + leftover_usd
    mid = cad_amount * fx_mid
    direct = mid * (1 - a.bank_spread)
    t = Ticket(
        cad_amount=cad_amount, cad_price=cad_price, usd_price=usd_price, fx_mid=fx_mid,
        journal_fee_cad=a.journal_fee, shares=shares, buy_fee_cad=buy_fee, leftover_cad=leftover_cad,
        sell_fee_usd=sell_fee, dividends_usd=dividends, leftover_usd=leftover_usd, gambit_usd=gambit,
        direct_usd=direct, mid_usd=mid, cost_vs_mid_usd=mid - gambit, saving_vs_direct_usd=gambit - direct,
        effective_rate=gambit / cad_amount,
    )
    if actual_usd is not None:
        t.actual_usd = actual_usd
        t.model_error_usd = actual_usd - gambit
    return t


def append_log(path: str | Path, ticket: Ticket, label: str = "") -> Path:
    """Append a ticket to a CSV log, to build a record of paper and real tests."""
    path = Path(path)
    row = {"logged_at": datetime.now().isoformat(timespec="seconds"), "label": label, **asdict(ticket)}
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return path


def live_quotes(cad_ticker: str = "DLR.TO", usd_ticker: str = "DLR-U.TO", fx_ticker: str = "CADUSD=X") -> dict:
    """Current ask (CAD listing), bid (USD listing) and FX rate from yfinance.

    Quotes are only meaningful while the TSX is open (9:30 am to 4 pm ET).
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("Install yfinance (pip install yfinance) for --live.") from exc

    def info(t):
        return yf.Ticker(t).info or {}

    cad, usd, fx = info(cad_ticker), info(usd_ticker), info(fx_ticker)
    ask = cad.get("ask") or cad.get("regularMarketPrice")
    bid = usd.get("bid") or usd.get("regularMarketPrice")
    rate = fx.get("regularMarketPrice") or fx.get("bid")
    if not (ask and bid and rate):
        raise ValueError("Could not get live quotes; pass --cad-price, --usd-price and --fx instead.")
    return {"cad_price": float(ask), "usd_price": float(bid), "fx_mid": float(rate),
            "ask_size": cad.get("askSize"), "bid_size": usd.get("bidSize")}
