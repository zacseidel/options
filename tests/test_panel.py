import pandas as pd

from market.store.panel import split_factors, total_return_index

SESSIONS = pd.DatetimeIndex(pd.bdate_range("2024-06-03", periods=6))


def test_split_factor_applies_only_before_ex_date():
    splits = pd.DataFrame([{"security_id": "NVDA", "ex_date": SESSIONS[3], "split_from": 1, "split_to": 10}])
    factor = split_factors(splits, SESSIONS, pd.Index(["NVDA", "AAPL"]))
    assert list(factor["NVDA"]) == [10, 10, 10, 1, 1, 1]
    assert (factor["AAPL"] == 1).all()
    raw = pd.Series([1200.0, 1210, 1190, 121, 122, 120], index=SESSIONS)
    adjusted = raw / factor["NVDA"]
    assert adjusted.round(2).tolist() == [120.0, 121.0, 119.0, 121.0, 122.0, 120.0]


def test_total_return_reinvests_dividend_on_ex_date():
    close = pd.DataFrame({"KO": [100.0, 100, 99, 99, 99, 99]}, index=SESSIONS)
    dividends = pd.DataFrame([{"security_id": "KO", "ex_date": SESSIONS[2], "amount": 1.0}])
    factor = pd.DataFrame(1.0, index=SESSIONS, columns=["KO"])
    tr = total_return_index(close, dividends, factor)["KO"]
    # Price fell by exactly the dividend on the ex-date: total return is flat.
    assert tr.round(10).tolist() == [1.0] * 6


def test_total_return_dividend_is_split_adjusted():
    # 2:1 split at session 3; a $2 pre-split dividend at session 1 is $1 per post-split share.
    close = pd.DataFrame({"X": [50.0, 49, 49, 49, 49, 49]}, index=SESSIONS)     # already split-adjusted
    dividends = pd.DataFrame([{"security_id": "X", "ex_date": SESSIONS[1], "amount": 2.0}])
    factor = pd.DataFrame({"X": [2.0, 2, 2, 1, 1, 1]}, index=SESSIONS)
    tr = total_return_index(close, dividends, factor)["X"]
    assert round(tr.iloc[1], 10) == 1.0
