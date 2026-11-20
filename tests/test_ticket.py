import sys
import types

import numpy as np
import pandas as pd
import pytest

from norbert_optimizer.cli import main
from norbert_optimizer.models import Assumptions, simulate
from norbert_optimizer.data import align
from norbert_optimizer.ticket import append_log, live_quotes, make_ticket


def test_ticket_hand_calculation():
    a = Assumptions(bank_spread=0.015, commission=0, journal_fee=9.95, slippage_bps=0)
    t = make_ticket(10_000, cad_price=14.0, usd_price=10.0, fx_mid=0.7143, a=a)
    # 9,990.05 CAD buys 713 shares (9,982 CAD); 8.05 CAD left goes through direct conversion
    assert t.shares == 713
    assert t.leftover_cad == pytest.approx(8.05)
    assert t.leftover_usd == pytest.approx(8.05 * 0.7143 * 0.985)
    assert t.gambit_usd == pytest.approx(7130 + 8.05 * 0.7143 * 0.985)
    assert t.direct_usd == pytest.approx(10_000 * 0.7143 * 0.985)
    assert t.cost_vs_mid_usd == pytest.approx(t.mid_usd - t.gambit_usd)


def test_ticket_matches_simulator():
    idx = pd.bdate_range("2025-01-01", periods=10)
    rng = np.random.default_rng(1)
    fx = pd.Series(0.72 + rng.normal(0, 0.002, 10), index=idx)
    cad = 10 / fx
    df = align(cad, cad * fx, fx)
    a = Assumptions(bank_spread=0.015, commission=4.95, journal_fee=9.95, delay_days=3, slippage_bps=5)
    r = simulate(df, 10_000, a)
    slip = 5 / 10_000
    t = make_ticket(10_000, cad.iloc[0] * (1 + slip), (cad * fx).iloc[3] * (1 - slip), fx.iloc[0], a)
    assert t.gambit_usd == pytest.approx(r["gambit_usd"].iloc[0])


def test_actual_result_and_log(tmp_path):
    a = Assumptions(commission=0, slippage_bps=0)
    t = make_ticket(5_000, 14.0, 10.0, 0.7143, a, actual_usd=3_560.0)
    assert t.model_error_usd == pytest.approx(3_560.0 - t.gambit_usd)
    path = append_log(tmp_path / "log.csv", t, "test")
    append_log(path, t, "again")
    rows = pd.read_csv(path)
    assert len(rows) == 2 and rows["label"].tolist() == ["test", "again"]


def test_live_quotes_with_fake_yfinance(monkeypatch):
    data = {"DLR.TO": {"ask": 14.01, "askSize": 5000}, "DLR-U.TO": {"bid": 10.02, "bidSize": 3000},
            "CADUSD=X": {"regularMarketPrice": 0.7150}}
    fake = types.SimpleNamespace(Ticker=lambda t: types.SimpleNamespace(info=data[t]))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    q = live_quotes()
    assert (q["cad_price"], q["usd_price"], q["fx_mid"], q["ask_size"]) == (14.01, 10.02, 0.7150, 5000)


def test_cli_ticket_manual_prices(capsys):
    assert main(["ticket", "--amount", "10000", "--broker", "questrade", "--cad-price", "14.0",
                 "--usd-price", "10.0", "--fx", "0.7143", "--actual-usd", "7130"]) == 0
    out = capsys.readouterr().out
    assert "Buy 713 shares" in out and "Actually received" in out


def test_cli_ticket_refuses_stock_at_dlr_only_broker():
    with pytest.raises(SystemExit):
        main(["ticket", "--amount", "10000", "--broker", "wealthsimple", "--pair", "RY",
              "--cad-price", "200", "--usd-price", "145", "--fx", "0.72"])
