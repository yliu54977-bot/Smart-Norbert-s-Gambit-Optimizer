import pandas as pd
import pytest

from norbert_optimizer.data import align, load_csv
from norbert_optimizer.models import Assumptions, bank_usd, simulate
from norbert_optimizer.stats import break_even_amount, summarize


def flat_market(days=10, cad_price=10.0, usd_price=7.5, cadusd=0.75):
    """A market where prices never move and the two listings are at parity."""
    idx = pd.bdate_range("2025-01-01", periods=days)
    return align(
        pd.Series(cad_price, index=idx),
        pd.Series(usd_price, index=idx),
        pd.Series(cadusd, index=idx),
    )


def test_bank_conversion():
    assert bank_usd(1000, 0.75, 0.02) == pytest.approx(735.0)


def test_gambit_flat_market_hand_calculation():
    df = flat_market()
    a = Assumptions(bank_spread=0.02, commission_cad=10, commission_usd=10, delay_days=4)
    r = simulate(df, 10_000, a)
    # 9,990 CAD buys 999 shares at 10 CAD; 0 CAD left over.
    # Sell 999 x 7.50 = 7,492.50 USD, minus 10 USD commission.
    assert r["shares"].iloc[0] == 999
    assert r["gambit_usd"].iloc[0] == pytest.approx(7482.50)
    assert r["bank_usd"].iloc[0] == pytest.approx(7350.00)
    assert r["difference_usd"].iloc[0] == pytest.approx(132.50)


def test_leftover_cash_goes_through_bank():
    df = flat_market(cad_price=3.0, usd_price=2.25)
    a = Assumptions(bank_spread=0.0, commission_cad=0, commission_usd=0, delay_days=1)
    r = simulate(df, 100, a)
    # 33 shares (99 CAD), 1 CAD left -> 0.75 USD; 33 x 2.25 = 74.25 USD.
    assert r["gambit_usd"].iloc[0] == pytest.approx(75.0)


def test_sell_uses_price_after_delay():
    idx = pd.bdate_range("2025-01-01", periods=6)
    usd = pd.Series([7.5, 7.5, 7.5, 7.5, 8.0, 8.0], index=idx)
    df = align(pd.Series(10.0, index=idx), usd, pd.Series(0.75, index=idx))
    a = Assumptions(bank_spread=0, commission_cad=0, commission_usd=0, delay_days=4)
    r = simulate(df, 1000, a)
    assert len(r) == 2
    assert r["sell_date"].iloc[0] == idx[4]
    assert r["gambit_usd"].iloc[0] == pytest.approx(100 * 8.0)


def test_small_amount_favours_bank():
    r = simulate(flat_market(), 200, Assumptions())
    assert (r["difference_usd"] < 0).all()


def test_break_even_flat_market():
    df = flat_market()
    a = Assumptions(bank_spread=0.02, commission_cad=10, commission_usd=10, delay_days=4)
    be = break_even_amount(df, simulate, a)
    assert be is not None
    assert simulate(df, be + 20, a)["difference_usd"].mean() > 0
    assert simulate(df, be - 20, a)["difference_usd"].mean() <= 0


def test_summary_fields():
    s = summarize(simulate(flat_market(), 10_000, Assumptions()), 10_000)
    assert s["start_dates"] == 6
    assert s["gambit_win_rate"] == 1.0


def test_invalid_inputs():
    with pytest.raises(ValueError):
        simulate(flat_market(), 5, Assumptions())  # below commission
    with pytest.raises(ValueError):
        simulate(flat_market(days=3), 1000, Assumptions(delay_days=4))
    with pytest.raises(ValueError):
        Assumptions(bank_spread=1.5)


def test_align_drops_missing_days():
    idx = pd.bdate_range("2025-01-01", periods=5)
    usd = pd.Series([7.5, None, 7.5, 7.5, 7.5], index=idx)
    df = align(pd.Series(10.0, index=idx), usd, pd.Series(0.75, index=idx))
    assert len(df) == 4


def test_derive_usd_price():
    from norbert_optimizer.data import derive_usd_price

    idx = pd.bdate_range("2025-01-01", periods=3)
    usd = derive_usd_price(pd.Series([14.0, 14.2, 14.1], index=idx), pd.Series([0.7, 0.7, 0.71], index=idx))
    assert list(usd.round(4)) == [9.8, 9.94, 10.011]


def test_load_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("date,cad_price,usd_price,cadusd\n2025-01-02,10,7.5,0.75\n2025-01-03,10,7.5,0.75\n")
    assert list(load_csv(p).columns) == ["cad_price", "usd_price", "cadusd"]
