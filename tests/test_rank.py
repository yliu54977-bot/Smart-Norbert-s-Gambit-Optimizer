import sys
import types

import numpy as np
import pandas as pd
import pytest

from norbert_optimizer import data as data_mod
from norbert_optimizer.cli import main
from norbert_optimizer.data import pair_frame
from norbert_optimizer.models import Assumptions
from norbert_optimizer.rank import best_by_amount, build_frames, rank_pairs, recommend
from norbert_optimizer.universe import UNIVERSE, Pair, find_pair

CALM = Pair("Calm Co", "CALM.TO", "CALM")
WILD = Pair("Wild Co", "WILD.TO", "WILD")
DLRX = Pair("Dollar ETF", "DLRX.TO", "DLRX-U.TO", "etf", derive_usd=True)


def make_wide(days=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=days)
    fx = 0.73 * np.exp(np.cumsum(rng.normal(0, 0.003, days)))
    calm = 50 * np.exp(np.cumsum(rng.normal(0, 0.003, days)))   # low volatility, in USD
    wild = 50 * np.exp(np.cumsum(rng.normal(0, 0.03, days)))    # high volatility, in USD
    return pd.DataFrame(
        {
            "CADUSD=X": fx,
            "CALM.TO": calm / fx, "CALM": calm,
            "WILD.TO": wild / fx, "WILD": wild,
            "DLRX.TO": 10 / fx,
        },
        index=pd.Index(idx, name="date"),
    )


def test_universe_tickers_unique_and_findable():
    cads = [p.cad for p in UNIVERSE]
    assert len(cads) == len(set(cads))
    assert find_pair("ry").cad == "RY.TO"
    assert find_pair("DLR.TO").derive_usd
    with pytest.raises(KeyError):
        find_pair("NOPE")


def test_pair_frame_derives_missing_usd():
    df, derived = pair_frame(make_wide(), DLRX)
    assert derived
    assert np.allclose(df["usd_price"], 10.0)


def test_ranking_prefers_low_risk_pair():
    frames = build_frames(make_wide(), [CALM, WILD, DLRX])
    table = rank_pairs(frames, 10_000, Assumptions(), with_break_even=False)
    assert set(table["cad_ticker"]) == {"CALM.TO", "WILD.TO", "DLRX.TO"}
    assert table.iloc[-1]["cad_ticker"] == "WILD.TO"  # widest spread of outcomes ranks last
    assert table["p5_savings_usd"].is_monotonic_decreasing


def test_recommend_bank_for_tiny_amounts():
    frames = build_frames(make_wide(), [CALM, DLRX])
    rec = recommend(rank_pairs(frames, 300, Assumptions(), with_break_even=False))
    assert rec["method"] == "Bank"


def test_best_by_amount_switches_from_bank():
    frames = build_frames(make_wide(), [CALM, DLRX])
    t = best_by_amount(frames, [300, 50_000], Assumptions())
    assert t.iloc[0]["recommended"] == "Bank"
    assert t.iloc[1]["recommended"].startswith("Norbert's Gambit")


def test_cli_rank_with_data_file(tmp_path, monkeypatch, capsys):
    wide = make_wide()
    path = tmp_path / "u.csv"
    wide.to_csv(path)
    monkeypatch.setattr("norbert_optimizer.cli.UNIVERSE", [CALM, WILD, DLRX])
    assert main(["rank", "--amount", "10000", "--data", str(path), "--out", str(tmp_path / "o"),
                 "--amounts", "1000,10000"]) == 0
    out = capsys.readouterr().out
    assert "Recommended:" in out
    assert (tmp_path / "o" / "ranking.csv").exists() and (tmp_path / "o" / "ranking.png").exists()


def test_download_universe_with_fake_yfinance(monkeypatch):
    wide = make_wide(days=30)

    class FakeTicker:
        def __init__(self, t):
            self.t = t

        def history(self, **kwargs):
            if self.t not in wide:
                return pd.DataFrame()
            idx = wide.index.tz_localize("America/Toronto")
            div = np.zeros(len(idx))
            div[10] = 0.25 if self.t == "CALM" else 0
            return pd.DataFrame({"Close": wide[self.t].to_numpy(), "Dividends": div}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    got = data_mod.download_universe([CALM, DLRX], "2024-01-01", "2024-03-01")
    assert {"CADUSD=X", "CALM.TO", "CALM", "DLRX.TO", "div:CALM"} <= set(got.columns)
    assert got["div:CALM"].dropna().tolist() == [0.25]
    df, derived = pair_frame(got, CALM)
    assert not derived and df["usd_dividend"].sum() == pytest.approx(0.25)
