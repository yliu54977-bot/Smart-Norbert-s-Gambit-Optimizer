import numpy as np
import pandas as pd
import pytest

from norbert_optimizer.data import align, clean_pair, derive_usd_price, load_csv
from norbert_optimizer.models import Assumptions, bank_usd, max_affordable_shares, simulate
from norbert_optimizer.stats import break_even_amount, summarize

NO_SLIP = dict(slippage_bps=0)


def flat_market(days=10, cad_price=10.0, usd_price=7.5, cadusd=0.75, divs=None):
    """A market where prices never move and the two listings are at parity."""
    idx = pd.bdate_range("2025-01-01", periods=days)
    return align(
        pd.Series(cad_price, index=idx),
        pd.Series(usd_price, index=idx),
        pd.Series(cadusd, index=idx),
        None if divs is None else pd.Series(divs, index=idx),
    )


def test_bank_conversion():
    assert bank_usd(1000, 0.75, 0.02) == pytest.approx(735.0)


def test_gambit_flat_market_hand_calculation():
    a = Assumptions(bank_spread=0.02, commission=10, delay_days=4, **NO_SLIP)
    r = simulate(flat_market(), 10_000, a)
    # 9,990 CAD buys 999 shares at 10 CAD; sell 999 x 7.50 = 7,492.50 USD, minus 10 USD.
    assert r["shares"].iloc[0] == 999
    assert r["gambit_usd"].iloc[0] == pytest.approx(7482.50)
    assert r["bank_usd"].iloc[0] == pytest.approx(7350.00)
    assert r["difference_usd"].iloc[0] == pytest.approx(132.50)


def test_slippage_hand_calculation():
    a = Assumptions(bank_spread=0.0, commission=0, delay_days=1, slippage_bps=100)  # 1% each way
    r = simulate(flat_market(cad_price=10.0, usd_price=7.5), 1010, a)
    # buy at 10.10 -> 100 shares; sell at 7.425 -> 742.50 USD
    assert r["shares"].iloc[0] == 100
    assert r["gambit_usd"].iloc[0] == pytest.approx(742.50)


def test_leftover_cash_goes_through_bank():
    a = Assumptions(bank_spread=0.0, commission=0, delay_days=1, **NO_SLIP)
    r = simulate(flat_market(cad_price=3.0, usd_price=2.25), 100, a)
    # 33 shares (99 CAD), 1 CAD left -> 0.75 USD; 33 x 2.25 = 74.25 USD.
    assert r["gambit_usd"].iloc[0] == pytest.approx(75.0)


def test_sell_uses_price_after_delay():
    idx = pd.bdate_range("2025-01-01", periods=6)
    usd = pd.Series([7.5, 7.5, 7.5, 7.5, 8.0, 8.0], index=idx)
    df = align(pd.Series(10.0, index=idx), usd, pd.Series(0.75, index=idx))
    a = Assumptions(bank_spread=0, commission=0, delay_days=4, **NO_SLIP)
    r = simulate(df, 1000, a)
    assert len(r) == 2
    assert r["sell_date"].iloc[0] == idx[4]
    assert r["gambit_usd"].iloc[0] == pytest.approx(100 * 8.0)


def test_dividend_received_only_inside_holding_window():
    divs = [0, 0, 0.5, 0, 0, 0, 0, 0, 0, 0]  # ex-date on day 2
    a = Assumptions(bank_spread=0, commission=0, delay_days=2, **NO_SLIP)
    r = simulate(flat_market(divs=divs), 1000, a)
    # Start day 0 holds days 1-2 -> gets it; start day 1 -> gets it; start day 2 -> ex-date not after start.
    got = (r["gambit_usd"] - 750).round(6).tolist()
    assert got[:3] == [50.0, 50.0, 0.0]


def test_per_share_fee_with_min_and_max():
    a = Assumptions(commission=0, per_share=0.01, commission_min=4.95, commission_max=9.95)
    fees = a.trade_fee(np.array([0, 100, 700, 5000]))
    assert fees.tolist() == pytest.approx([0, 4.95, 7.0, 9.95])


def test_max_affordable_shares_respects_fee():
    a = Assumptions(commission=0, per_share=0.01, commission_min=4.95, commission_max=9.95, **NO_SLIP)
    s = max_affordable_shares(1000.0, np.array([10.0]), a)
    assert s[0] == 99  # 99 x 10 + 4.95 = 994.95 fits; 100 shares would not
    assert s[0] * 10 + a.trade_fee(s)[0] <= 1000


def test_immediate_sale_has_no_price_risk():
    idx = pd.bdate_range("2025-01-01", periods=30)
    rng = np.random.default_rng(0)
    fx = pd.Series(0.73 + rng.normal(0, 0.005, 30), index=idx)
    cad = pd.Series(100 + rng.normal(0, 3, 30), index=idx)
    df = align(cad, cad * fx, fx)
    r0 = simulate(df, 10_000, Assumptions(delay_days=0))
    r4 = simulate(df, 10_000, Assumptions(delay_days=4))
    assert r0["difference_usd"].std() < r4["difference_usd"].std()


def test_small_amount_favours_bank():
    r = simulate(flat_market(), 200, Assumptions())
    assert (r["difference_usd"] < 0).all()


def test_break_even_flat_market():
    df = flat_market()
    a = Assumptions(bank_spread=0.02, commission=10, delay_days=4, **NO_SLIP)
    be = break_even_amount(df, simulate, a)
    assert be is not None
    assert simulate(df, be + 20, a)["difference_usd"].mean() > 0
    assert simulate(df, be - 20, a)["difference_usd"].mean() <= 0


def test_summary_fields():
    s = summarize(simulate(flat_market(), 10_000, Assumptions()), 10_000)
    assert s["start_dates"] == 6
    assert s["gambit_win_rate"] == 1.0
    assert s["p5_savings_usd"] <= s["mean_savings_usd"] <= s["p95_savings_usd"]


def test_invalid_inputs():
    with pytest.raises(ValueError):
        simulate(flat_market(), 5, Assumptions())  # cannot buy one share
    with pytest.raises(ValueError):
        simulate(flat_market(days=3), 1000, Assumptions(delay_days=4))
    with pytest.raises(ValueError):
        Assumptions(bank_spread=1.5)
    with pytest.raises(ValueError):
        Assumptions(commission_min=10, commission_max=5)


def test_align_drops_missing_days():
    idx = pd.bdate_range("2025-01-01", periods=5)
    usd = pd.Series([7.5, None, 7.5, 7.5, 7.5], index=idx)
    df = align(pd.Series(10.0, index=idx), usd, pd.Series(0.75, index=idx))
    assert len(df) == 4


def test_clean_pair_flags_bad_quotes_and_simulate_skips_them():
    df = flat_market(days=10)
    df.iloc[5, df.columns.get_loc("usd_price")] = 9.0  # 20% off: bad quote
    cleaned, flagged = clean_pair(df)
    assert flagged == 1 and len(cleaned) == 10
    r = simulate(cleaned, 1000, Assumptions(delay_days=1))
    # windows [4,5] and [5,6] touch the bad day; 9 start dates minus 2
    assert len(r) == 7 and df.index[4] not in r.index and df.index[5] not in r.index


def test_clean_pair_catches_one_sided_adjustment():
    # CAD history scaled down 10% (like a spin-off adjusted on one listing only)
    df = flat_market(days=10)
    df.iloc[:6, df.columns.get_loc("cad_price")] *= 0.9
    cleaned, flagged = clean_pair(df)
    assert flagged == 6
    assert (simulate(cleaned, 1000, Assumptions(delay_days=1)).index >= df.index[6]).all()


def test_derive_usd_price():
    idx = pd.bdate_range("2025-01-01", periods=3)
    usd = derive_usd_price(pd.Series([14.0, 14.2, 14.1], index=idx), pd.Series([0.7, 0.7, 0.71], index=idx))
    assert list(usd.round(4)) == [9.8, 9.94, 10.011]


def test_load_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("date,cad_price,usd_price,cadusd\n2025-01-02,10,7.5,0.75\n2025-01-03,10,7.5,0.75\n")
    df = load_csv(p)
    assert list(df.columns) == ["cad_price", "usd_price", "cadusd", "usd_dividend"]
