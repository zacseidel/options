import numpy as np
import pandas as pd

from market.evaluate.options_engine import nav_from_paths
from market.methods import option_math as om
from market.methods.hold_rules import Trade
from market.methods.instruments.options import OptionData, simulate_window
from market.store.panel import Panel

SESSIONS = pd.bdate_range("2026-01-05", periods=30)          # Mon 2026-01-05 … Fri 2026-02-13
EXPIRIES = [pd.Timestamp("2026-01-23"), pd.Timestamp("2026-02-13"), pd.Timestamp("2027-06-18")]
VOL, RATE = 0.30, 0.04
HAIRCUT = {"base_pct": 0.03, "min_dollars": 0.05, "wide_dte": 180, "wide_abs_delta": 0.15, "wide_multiplier": 2.0}
LIQ = {"short": {"min_volume": 10, "min_transactions": 3}, "leap": {"min_volume": 2, "min_transactions": 1}}
SHORT = {"short_dte": [14, 21], "leap_dte": {"min": 365, "max": 800, "prefer": 540, "roll_below": 180}}


def market(prices: list[float]) -> OptionData:
    close = pd.DataFrame({"A": prices}, index=SESSIONS, dtype=float)
    ones = close * 0 + 1
    panel = Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                  volume=ones, tr=close / close.iloc[0], split_factor=ones)
    rows = []
    for s, spot in zip(SESSIONS, prices):
        for expiry in EXPIRIES:
            if expiry < s:
                continue
            t = (expiry - s).days / 365
            for kind in "CP":
                for strike in range(60, 141, 5):
                    px = float(om.price(kind, spot, strike, t, RATE, 0.0, VOL)) if t > 0 else \
                        max(spot - strike, 0) if kind == "C" else max(strike - spot, 0)
                    if px >= 0.05:
                        rows.append((s, "A", expiry, kind, float(strike), px, px, 100, 10))
    bars = pd.DataFrame(rows, columns=["session", "root", "expiry", "kind", "strike", "open", "close", "volume", "transactions"])
    divs = pd.DataFrame(columns=["security_id", "ex_date", "amount"])
    return OptionData(bars, panel, divs, RATE, HAIRCUT, LIQ)


def run(data, method, entry=1, exit_=20, mult=1.0):
    return simulate_window(data, "A", "A", SESSIONS[entry], SESSIONS[exit_] if exit_ is not None else None,
                           {**SHORT, **method}, mult)


def test_csp_expires_otm_and_resells_then_buys_back_at_window_end():
    res = run(market([100.0] * 30), {"instrument": "csp", "delta": -0.30})
    puts = [leg for leg in res.legs if leg.kind == "P"]
    assert [leg.close_reason for leg in puts] == ["expired", "window end"]
    assert puts[0].contract[1] == EXPIRIES[0] and puts[1].contract[1] == EXPIRIES[1]
    assert puts[1].open_date == SESSIONS[15]                 # the session after the expiry
    assert abs(puts[0].delta + 0.30) < 0.1
    assert 1.0 < res.exit_value < 1.05                       # premium + T-bill interest, less haircuts
    assert res.events["assigned"] == 0


def test_csp_assigned_holds_shares_to_window_end():
    prices = [100.0] * 5 + [80.0] * 25
    res = run(market(prices), {"instrument": "csp", "delta": -0.30})
    assert res.events["assigned"] == 1
    shares = [leg for leg in res.legs if leg.kind == "S"]
    assert len(shares) == 1 and shares[0].close_reason == "window end"
    assert len([leg for leg in res.legs if leg.kind == "P"]) == 1        # no puts after assignment
    assert res.exit_value < 0.95


def test_covered_call_called_away_rebuys():
    prices = [100.0] * 5 + [115.0] * 25
    res = run(market(prices), {"instrument": "covered_call", "delta": 0.30})
    assert res.events["called_away"] == 1
    shares = [leg for leg in res.legs if leg.kind == "S"]
    assert len(shares) == 2                                   # bought, called away, re-bought
    stock_only = 115.0 / 100.0
    assert res.exit_value < stock_only                        # the call capped the gain


def test_leap_tracks_stock_with_cash_and_delta():
    prices = list(np.linspace(100, 110, 30))
    data = market(prices)
    res = run(data, {"instrument": "leap", "delta": 0.80}, mult=0.0)
    leap = [leg for leg in res.legs if leg.kind == "C"][0]
    assert leap.contract[1] == EXPIRIES[2]
    stock_gain = prices[20] / prices[1] - 1
    assert 0.6 * stock_gain < res.exit_value - 1 < stock_gain
    # The doubled long-dated haircut costs ~3% of notional per round trip.
    costly = run(data, {"instrument": "leap", "delta": 0.80}, mult=1.0)
    assert 0.02 < res.exit_value - costly.exit_value < 0.05


def test_haircut_ordering():
    data = market([100.0] * 30)
    values = [run(data, {"instrument": "csp", "delta": -0.30}, mult=m).exit_value for m in (0.0, 1.0, 2.0)]
    assert values[0] > values[1] > values[2]


def test_open_window_marks_to_last_session():
    res = run(market([100.0] * 30), {"instrument": "diagonal", "delta": 0.80, "short_delta": 0.30}, exit_=None)
    assert res.exit_value is None and res.marks.index[-1] == SESSIONS[-1]
    assert {leg.qty > 0 for leg in res.legs if leg.kind == "C"} == {True, False}


def test_nav_from_paths_equal_capital():
    data = market([100.0] * 30)
    t = Trade("A", "A", SESSIONS[1].date(), SESSIONS[1], exit_session=SESSIONS[20])
    res = run(data, {"instrument": "csp", "delta": -0.30})
    nav = nav_from_paths([(t, res)], SESSIONS[1:])
    assert abs(nav["nav"].loc[SESSIONS[20]] - 100 * res.exit_value) < 1e-9
    assert nav["positions"].iloc[-1] == 0
