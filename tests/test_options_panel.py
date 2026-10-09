from datetime import date

import pandas as pd

from market.data.options import filter_panel, occ_ticker, option_root, parse_occ

BANDS = {
    "dte_min": 1,
    "dte_max": 800,
    "put_strike_pct": [0.60, 1.05],
    "call_strike_pct": [0.95, 1.40],
    "leap_dte_min": 240,
    "leap_call_strike_pct": [0.40, 1.00],
}
SESSION = date(2026, 10, 7)


def test_occ_round_trip():
    ticker = occ_ticker("AAPL", date(2026, 11, 20), "P", 150.0)
    assert ticker == "O:AAPL261120P00150000"
    parsed = parse_occ(pd.Series([ticker, "O:BRKB270115C00512500", "garbage"]))
    assert parsed.loc[0, "root"] == "AAPL"
    assert parsed.loc[0, "expiry"] == pd.Timestamp("2026-11-20")
    assert parsed.loc[0, "type"] == "P" and parsed.loc[0, "strike"] == 150.0
    assert parsed.loc[1, "root"] == "BRKB" and parsed.loc[1, "strike"] == 512.5
    assert parsed.loc[2].isna().all()


def test_option_root_drops_class_separator():
    assert option_root("BRK.B") == "BRKB"
    assert option_root("AAPL") == "AAPL"


def test_filter_keeps_only_band_rows():
    rows = pd.DataFrame({"ticker": [
        occ_ticker("AAPL", date(2026, 11, 20), "P", 90),    # 90% put, 44 DTE -> keep
        occ_ticker("AAPL", date(2026, 11, 20), "P", 50),    # 50% put -> drop (below band)
        occ_ticker("AAPL", date(2026, 11, 20), "C", 110),   # 110% call -> keep
        occ_ticker("AAPL", date(2026, 11, 20), "C", 70),    # deep ITM short-dated call -> drop
        occ_ticker("AAPL", date(2028, 1, 21), "C", 70),     # deep ITM LEAP call -> keep
        occ_ticker("AAPL", date(2029, 1, 19), "C", 100),    # beyond 800 DTE -> drop
        occ_ticker("AAPL1", date(2026, 11, 20), "P", 90),   # adjusted root -> drop
        occ_ticker("MSFT", date(2026, 11, 20), "P", 90),    # not in universe -> drop
    ]})
    kept = filter_panel(rows, SESSION, {"AAPL": 100.0}, BANDS)
    assert list(kept.index) == [0, 2, 4]
    assert kept.loc[0, "dte"] == 44
