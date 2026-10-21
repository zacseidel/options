from datetime import date

import pandas as pd

from market.data.options import filter_panel, occ_ticker, option_root, parse_occ

BANDS = {
    "short_dte": [7, 60],
    "put_strike_pct": [0.70, 1.02],
    "call_strike_pct": [0.98, 1.20],
    "leap_dte": [180, 800],
    "leap_call_strike_pct": [0.50, 1.00],
    "min_volume": 5,
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
    tickers = [
        occ_ticker("AAPL", date(2026, 11, 20), "P", 90),    # 90% put, 44 DTE -> keep
        occ_ticker("AAPL", date(2026, 11, 20), "P", 60),    # 60% put -> drop (below band)
        occ_ticker("AAPL", date(2026, 11, 20), "C", 110),   # 110% call -> keep
        occ_ticker("AAPL", date(2026, 11, 20), "C", 70),    # deep ITM short-dated call -> drop
        occ_ticker("AAPL", date(2028, 1, 21), "C", 70),     # deep ITM LEAP call -> keep
        occ_ticker("AAPL", date(2027, 2, 19), "C", 100),    # 135 DTE: between bands -> drop
        occ_ticker("AAPL", date(2029, 1, 19), "C", 100),    # beyond 800 DTE -> drop
        occ_ticker("AAPL1", date(2026, 11, 20), "P", 90),   # adjusted root -> drop
        occ_ticker("MSFT", date(2026, 11, 20), "P", 90),    # not in the option set -> drop
        occ_ticker("AAPL", date(2026, 11, 20), "P", 95),    # in band but volume 2 -> drop
    ]
    rows = pd.DataFrame({
        "ticker": tickers,
        "open": 1.0, "close": 1.1, "transactions": 4,
        "volume": [10] * 9 + [2],
    })
    kept = filter_panel(rows, SESSION, {"AAPL": 100.0}, BANDS)
    assert list(kept.index) == [0, 2, 4]
    assert list(kept.columns) == ["session", "root", "expiry", "kind", "strike", "open", "close", "volume", "transactions"]
    assert kept.loc[4, "kind"] == "C" and kept.loc[4, "strike"] == 70.0
    assert occ_ticker(kept.loc[0, "root"], kept.loc[0, "expiry"].date(), kept.loc[0, "kind"], kept.loc[0, "strike"]) == tickers[0]


def _client_error(code: str):
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": code, "Message": ""}}, "GetObject")


def test_recent_403_counts_as_unpublished():
    from market.data.option_panel import _unpublished
    today = date(2026, 10, 20)
    assert _unpublished(_client_error("403"), date(2026, 10, 20), today)
    assert _unpublished(_client_error("403"), date(2026, 10, 16), today)      # Friday, seen Monday
    assert not _unpublished(_client_error("403"), date(2026, 9, 1), today)    # old: a real entitlement error
    assert _unpublished(_client_error("NoSuchKey"), date(2026, 9, 1), today)
    assert not _unpublished(_client_error("SlowDown"), date(2026, 10, 20), today)
