"""Load and align price data.

Every model in this project works on one aligned DataFrame indexed by trading
date with three columns:

    cad_price  - price of the Canadian-dollar listing (e.g. DLR.TO), in CAD
    usd_price  - price of the US-dollar listing (e.g. DLR-U.TO), in USD
    cadusd     - USD received for 1 CAD (Yahoo ticker CADUSD=X)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ["cad_price", "usd_price", "cadusd"]


def align(cad_price: pd.Series, usd_price: pd.Series, cadusd: pd.Series) -> pd.DataFrame:
    """Join three price series on the dates they all share and drop gaps."""
    df = pd.concat(
        {"cad_price": cad_price, "usd_price": usd_price, "cadusd": cadusd},
        axis=1,
        join="inner",
    ).dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    df = df.sort_index()
    if df.empty:
        raise ValueError("No overlapping trading days with complete data.")
    if (df <= 0).any().any():
        raise ValueError("Prices and FX rates must be positive.")
    return df


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load an aligned dataset from a CSV with a `date` column."""
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")
    return align(df["cad_price"], df["usd_price"], df["cadusd"])


def derive_usd_price(cad_price: pd.Series, cadusd: pd.Series) -> pd.Series:
    """Estimate the USD listing's price as the CAD price converted at the FX rate.

    Used for DLR.TO / DLR-U.TO: both are units of the same fund, so the USD
    units trade at about the CAD price times CADUSD. Yahoo Finance has no
    history for DLR-U.TO, so this is the fallback.
    """
    df = pd.concat({"cad": cad_price, "fx": cadusd}, axis=1, join="inner").dropna()
    return df["cad"] * df["fx"]


def load_yfinance(
    cad_ticker: str,
    usd_ticker: str,
    start: str,
    end: str,
    fx_ticker: str = "CADUSD=X",
    derive_usd: bool = False,
) -> tuple[pd.DataFrame, bool]:
    """Download closing prices with yfinance and align them.

    Returns the aligned data and whether the USD price was derived from the
    CAD price and the FX rate (because the USD listing had too little data,
    or because `derive_usd` was set).
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("Install yfinance (pip install yfinance) or use --csv.") from exc

    def close(ticker: str) -> pd.Series:
        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        return hist["Close"] if not hist.empty else pd.Series(dtype=float)

    cad, fx = close(cad_ticker), close(fx_ticker)
    if cad.empty or fx.empty:
        raise ValueError(f"No data returned for {cad_ticker if cad.empty else fx_ticker}.")

    usd = pd.Series(dtype=float) if derive_usd else close(usd_ticker)
    derived = len(usd.dropna()) < 0.5 * len(cad.dropna())
    if derived:
        usd = derive_usd_price(cad, fx)
    return align(cad, usd, fx), derived
