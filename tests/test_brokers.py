import dataclasses

import numpy as np
import pandas as pd
import pytest

from norbert_optimizer.brokers import BROKERS, Broker, FxTier, get_broker
from norbert_optimizer.cli import main
from norbert_optimizer.data import align, fx_at_tsx_close
from norbert_optimizer.models import Assumptions, simulate
from norbert_optimizer.rank import broker_assumptions, build_frames, compare_brokers, rank_pairs
from norbert_optimizer.universe import Pair

DLR = Pair("Dollar ETF", "DLR.TO", "DLR-U.TO", "etf", derive_usd=True)
RY = Pair("Bank", "RY.TO", "RY")


def make_wide(days=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=days)
    fx = 0.73 * np.exp(np.cumsum(rng.normal(0, 0.003, days)))
    ry = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))
    return pd.DataFrame({"CADUSD=X": fx, "DLR.TO": 10 / fx, "RY.TO": ry / fx, "RY": ry},
                        index=pd.Index(idx, name="date"))


def test_every_broker_has_sources_and_valid_rules():
    for b in BROKERS.values():
        assert b.sources, b.key
        assert b.gambit in {"all", "dlr_only", "not_needed"}
        assert b.fx_tiers and all(0 <= t.spread < 0.05 for t in b.fx_tiers)


def test_tiered_fx_in_cad_and_usd():
    ws = get_broker("wealthsimple")
    assert ws.fx_spread(9_999, 0.73) == 0.015
    assert ws.fx_spread(10_000, 0.73) == 0.010
    assert ws.fx_spread(150_000, 0.73) == 0.0
    td = get_broker("td")  # thresholds in USD
    assert td.fx_spread(30_000, 0.73) == 0.0126   # 21,900 USD
    assert td.fx_spread(40_000, 0.73) == 0.0078   # 29,200 USD


def test_ibkr_minimum_fee_dominates_small_conversions():
    ib = get_broker("ibkr")
    assert ib.fx_spread(1_000, 0.73) == pytest.approx(2 / 730)
    assert ib.fx_spread(10_000_000, 0.73) == pytest.approx(0.00002)
    assert not ib.allows("DLR.TO")


def test_dlr_only_broker_skips_stocks():
    ws = get_broker("wealthsimple")
    assert ws.allows("DLR.TO") and not ws.allows("RY.TO")
    frames = build_frames(make_wide(), [DLR, RY])
    a = broker_assumptions(ws, 10_000, 0.73)
    table = rank_pairs(frames, 10_000, a, with_break_even=False, broker=ws)
    assert table["cad_ticker"].tolist() == ["DLR.TO"]


def test_journal_fee_comes_out_of_the_budget():
    idx = pd.bdate_range("2025-01-01", periods=8)
    df = align(pd.Series(10.0, index=idx), pd.Series(7.5, index=idx), pd.Series(0.75, index=idx))
    base = Assumptions(bank_spread=0, commission=0, delay_days=1, slippage_bps=0)
    r0 = simulate(df, 1000, base)
    r1 = simulate(df, 1000, base.with_(journal_fee=10))
    assert r0["gambit_usd"].iloc[0] == pytest.approx(750)
    assert r1["gambit_usd"].iloc[0] == pytest.approx(742.5)  # 990 CAD left -> 99 shares


def test_broker_delay_per_security():
    rbc = get_broker("rbc")
    assert rbc.delay_for("DLR.TO") == 0 and rbc.delay_for("RY.TO") == 3


def test_fx_at_tsx_close_removes_timing_noise():
    wide = make_wide()
    noisy = wide.copy()
    noisy["CADUSD=X"] = wide["CADUSD=X"] * (1 + np.random.default_rng(0).normal(0, 0.005, len(wide)))
    fx = fx_at_tsx_close(noisy)
    # DLR.TO = 10 / true fx, so the 4 pm rate should recover the true fx closely
    err = (fx / wide["CADUSD=X"] - 1).abs()
    assert err.median() < 0.002


def test_compare_brokers_picks_cheapest_and_ibkr_converts_directly():
    frames = build_frames(make_wide(), [DLR, RY])
    free = Broker("free", "Free Broker", commission=0, fx_tiers=(FxTier(float("inf"), 0.015),), dlr_delay=0)
    pricey = dataclasses.replace(free, key="pricey", name="Pricey Broker", commission=9.95, journal_fee=9.95)
    table = compare_brokers(frames, [pricey, get_broker("ibkr"), free], 50_000)
    assert table.iloc[0]["key"] in {"free", "ibkr"}
    row = table.set_index("key")
    assert row.loc["ibkr", "recommended"] == "Convert directly"
    assert row.loc["free", "recommended"].startswith("Norbert's Gambit")
    assert row.loc["free", "mean_cost_usd"] < row.loc["pricey", "mean_cost_usd"]


def test_cli_brokers_list_and_compare(tmp_path, monkeypatch, capsys):
    assert main(["brokers", "--list"]) == 0
    assert "Source: https://" in capsys.readouterr().out
    path = tmp_path / "u.csv"
    make_wide().to_csv(path)
    monkeypatch.setattr("norbert_optimizer.cli.UNIVERSE", [DLR, RY])
    assert main(["brokers", "--amount", "10000", "--data", str(path), "--out", str(tmp_path / "o"),
                 "--amounts", "1000,10000"]) == 0
    out = capsys.readouterr().out
    assert "Cheapest:" in out and (tmp_path / "o" / "brokers.png").exists()
    assert main(["rank", "--amount", "10000", "--broker", "questrade", "--data", str(path),
                 "--out", str(tmp_path / "r"), "--amounts", "10000"]) == 0
    assert "Questrade's direct conversion" in capsys.readouterr().out
