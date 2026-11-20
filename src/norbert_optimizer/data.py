"""Load, clean and align price data.

Two formats are used:

* A **pair frame**: what the simulator works on. Indexed by trading date with
  columns `cad_price`, `usd_price`, `cadusd` (USD per 1 CAD) and
  `usd_dividend` (USD dividend per share with that ex-date, 0 otherwise).

* A **wide frame**: one column per Yahoo ticker with closing prices, plus
  `div:<ticker>` columns with dividends for the USD listings. It holds the whole
  universe and is what `download_universe` returns and `--data` files contain.

Prices are Yahoo's split-adjusted closes (not dividend-adjusted); dividends are
added separately by the simulator.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from .universe import Pair

FX_TICKER = "CADUSD=X"
REQUIRED_COLUMNS = ["cad_price", "usd_price", "cadusd"]


def _clean_index(s: pd.Series) -> pd.Series:
    s = s.copy()
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")]


def align(
    cad_price: pd.Series,
    usd_price: pd.Series,
    cadusd: pd.Series,
    usd_dividend: pd.Series | None = None,
) -> pd.DataFrame:
    """Join the price series on the dates they all share and drop gaps."""
    df = pd.concat(
        {
            "cad_price": _clean_index(cad_price),
            "usd_price": _clean_index(usd_price),
            "cadusd": _clean_index(cadusd),
        },
        axis=1,
        join="inner",
    ).dropna()
    df.index.name = "date"
    df = df.sort_index()
    if df.empty:
        raise ValueError("No overlapping trading days with complete data.")
    if (df <= 0).any().any():
        raise ValueError("Prices and FX rates must be positive.")
    if usd_dividend is not None:
        div = _clean_index(usd_dividend.dropna())
        df["usd_dividend"] = div.reindex(df.index).fillna(0.0)
    else:
        df["usd_dividend"] = 0.0
    return df


def derive_usd_price(cad_price: pd.Series, cadusd: pd.Series) -> pd.Series:
    """Estimate the USD listing's price as the CAD price converted at the FX rate.

    Used for DLR.TO / DLR-U.TO: both are units of the same fund, so the USD
    units trade at about the CAD price times CADUSD. Yahoo Finance has no
    history for DLR-U.TO, so this is the fallback.
    """
    df = pd.concat({"cad": _clean_index(cad_price), "fx": _clean_index(cadusd)}, axis=1, join="inner").dropna()
    return df["cad"] * df["fx"]


def clean_pair(df: pd.DataFrame, max_gap: float = 0.03) -> tuple[pd.DataFrame, int]:
    """Flag days where the two listings disagree by more than `max_gap`.

    Both listings are the same share, so USD price / (CAD price x CADUSD)
    should be close to 1. A big gap means bad data: a wrong quote, or a
    corporate action that Yahoo adjusted on one listing but not the other
    (TC Energy's 2024 South Bow spin-off shifted TRP.TO's history by about 10%
    while TRP's stayed unadjusted). Simulating across such days would create
    fake gains or losses.

    Rows are kept and an `ok` column is added; `simulate` skips every start
    date whose holding window touches a flagged day. Returns the frame and the
    number of flagged days.
    """
    ratio = df["usd_price"] / (df["cad_price"] * df["cadusd"])
    out = df.copy()
    out["ok"] = (ratio - 1).abs() <= max_gap
    return out, int((~out["ok"]).sum())


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load one pair from a CSV with columns date, cad_price, usd_price, cadusd
    and optionally usd_dividend."""
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")
    return align(df["cad_price"], df["usd_price"], df["cadusd"], df.get("usd_dividend"))


def load_wide_csv(path: str | Path) -> pd.DataFrame:
    """Load a universe file (one column per ticker, `div:` columns for dividends)."""
    wide = pd.read_csv(path, parse_dates=["date"], index_col="date")
    if FX_TICKER not in wide.columns:
        raise ValueError(f"Universe file needs a {FX_TICKER} column.")
    return wide


def pair_frame(wide: pd.DataFrame, pair: Pair) -> tuple[pd.DataFrame, bool]:
    """Build the pair frame for one pair from a wide frame.

    Returns the frame and whether the USD price was derived from the FX rate.
    """
    if pair.cad not in wide.columns:
        raise KeyError(f"No data for {pair.cad}")
    cad, fx = wide[pair.cad].dropna(), wide[FX_TICKER].dropna()
    usd = wide[pair.usd].dropna() if pair.usd in wide.columns else pd.Series(dtype=float)
    derived = pair.derive_usd or len(usd) < 0.5 * len(cad)
    if derived:
        usd = derive_usd_price(cad, fx)
    div = wide.get(f"div:{pair.usd}")
    return align(cad, usd, fx, div), derived


def download_universe(
    pairs: list[Pair], start: str, end: str, fx_ticker: str = FX_TICKER
) -> pd.DataFrame:
    """Download closes (and USD-listing dividends) for every pair with yfinance."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("Install yfinance (pip install yfinance) or pass --data.") from exc

    usd_tickers = {p.usd for p in pairs if not p.derive_usd}
    tickers = [fx_ticker] + sorted({p.cad for p in pairs} | usd_tickers)
    cols: dict[str, pd.Series] = {}
    for t in tickers:
        hist = yf.Ticker(t).history(start=start, end=end, auto_adjust=False, actions=True)
        if hist.empty:
            warnings.warn(f"No data returned for {t}; pairs using it are skipped.")
            continue
        cols[t] = _clean_index(hist["Close"])
        if t in usd_tickers and "Dividends" in hist:
            div = _clean_index(hist["Dividends"])
            cols[f"div:{t}"] = div[div > 0]
    wide = pd.DataFrame(cols).sort_index()
    wide.index.name = "date"
    return wide


def load_yfinance(
    cad_ticker: str,
    usd_ticker: str,
    start: str,
    end: str,
    fx_ticker: str = FX_TICKER,
    derive_usd: bool = False,
) -> tuple[pd.DataFrame, bool]:
    """Download one pair with yfinance. Returns the pair frame and whether the
    USD price was derived (USD listing missing, or `derive_usd` set)."""
    pair = Pair(f"{cad_ticker}/{usd_ticker}", cad_ticker, usd_ticker, derive_usd=derive_usd)
    wide = download_universe([pair], start, end, fx_ticker)
    return pair_frame(wide, pair)
