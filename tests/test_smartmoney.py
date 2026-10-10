from datetime import date

import numpy as np
import pandas as pd

from market.data.securities import EARLIEST, map_tickers, ticker_history_rows
from market.smartmoney import congress, hedge
from market.smartmoney.ingest import parse_form_idx
from market.store.panel import Panel


# ------------------------------------------------------------------ security master rules

def test_last_event_ticker_survives_when_current_ticker_differs():
    # Fiserv: events end at FI (2023) but the lookup says FISV today.
    events = [{"type": "ticker_change", "date": "2003-09-10", "ticker_change": {"ticker": "FISV"}},
              {"type": "ticker_change", "date": "2023-06-07", "ticker_change": {"ticker": "FI"}}]
    rows = ticker_history_rows("F", "FISV", None, events)
    fi = [r for r in rows if r["ticker"] == "FI"]
    assert fi and fi[0]["valid_from"] == date(2023, 6, 7) and fi[0]["priority"] == 2


def test_current_ticker_covers_time_before_a_recent_first_event():
    # Honeywell: events start with a temporary HONI in 2026; HON before that.
    events = [{"type": "ticker_change", "date": "2026-06-15", "ticker_change": {"ticker": "HONI"}},
              {"type": "ticker_change", "date": "2026-06-29", "ticker_change": {"ticker": "HON"}}]
    rows = ticker_history_rows("H", "HON", None, events)
    early = [r for r in rows if r["ticker"] == "HON" and r["valid_from"] == EARLIEST]
    assert early and early[0]["valid_to"] == date(2026, 6, 15) and early[0]["priority"] == 2


def test_map_tickers_prefers_priority_and_uses_slack():
    history = pd.DataFrame([
        {"security_id": "A", "ticker": "X", "valid_from": "1900-01-01", "valid_to": "2024-01-01", "priority": 1, "type": "CS"},
        {"security_id": "B", "ticker": "X", "valid_from": "2024-01-01", "valid_to": None, "priority": 1, "type": "CS"},
        {"security_id": "C", "ticker": "X", "valid_from": "1900-01-01", "valid_to": None, "priority": 2, "type": "CS"},
        {"security_id": "D", "ticker": "Y", "valid_from": "2025-01-01", "valid_to": None, "priority": 1, "type": "CS"},
    ])
    got = map_tickers(history, pd.Series(["X", "X", "Y", "Z"]),
                      pd.Series(pd.to_datetime(["2023-06-01", "2025-06-01", "2024-11-01", "2025-01-01"])))
    assert list(got) == ["A", "B", "D", None]          # Y: within 120 days of its first use


# ------------------------------------------------------------------ Congress lots

SESSIONS = pd.bdate_range("2025-01-06", periods=40)


def _panel(prices: dict[str, list[float]]) -> Panel:
    close = pd.DataFrame(prices, index=SESSIONS, dtype=float)
    ones = close * 0 + 1
    return Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                 volume=ones, tr=close, split_factor=ones)


def _history(ids):
    return pd.DataFrame([{"security_id": s, "ticker": s, "valid_from": "1900-01-01", "valid_to": None,
                          "priority": 1, "type": "CS" if s != "SPY" else "ETF"} for s in ids])


def test_lot_enters_after_disclosure_and_closes_on_sale_disclosure():
    up = [10.0 + i for i in range(40)]
    panel = _panel({"AAA": up, "SPY": [100.0] * 40})
    trades = pd.DataFrame([
        {"member_id": "m1", "member": "M One", "chamber": "house", "party": "", "state": "", "ticker": "AAA",
         "tx_type": "P", "traded": SESSIONS[0], "disclosed": SESSIONS[2], "amount": 10_000},
        {"member_id": "m1", "member": "M One", "chamber": "house", "party": "", "state": "", "ticker": "AAA",
         "tx_type": "S", "traded": SESSIONS[8], "disclosed": SESSIONS[10], "amount": 10_000},
    ])
    data = congress.build(trades, panel, _history(["AAA", "SPY"]))
    lot = data.lots.iloc[0]
    assert lot["pos"] == 3 and lot["exit_pos"] == 11          # the sessions after each disclosure
    lots = congress.lot_returns(data, 30)
    assert np.isclose(lots["ret"].iloc[0], up[11] / up[3] - 1) and not lots["open"].iloc[0]
    assert congress.lot_returns(data, 2).empty                  # not public yet


def test_member_needs_minimum_lots_to_rank():
    panel = _panel({"AAA": [10.0 + i for i in range(40)], "SPY": [100.0] * 40})
    rows = [{"member_id": "m1", "member": "M", "chamber": "house", "party": "", "state": "", "ticker": "AAA",
             "tx_type": "P", "traded": SESSIONS[i], "disclosed": SESSIONS[i], "amount": 1000} for i in range(congress.MIN_LOTS - 1)]
    data = congress.build(pd.DataFrame(rows), panel, _history(["AAA", "SPY"]))
    scores = congress.member_scores(data, 30)
    assert not scores["rankable"].any() and scores["rank"].isna().all()


def test_holding_bought_before_the_window_counts_from_its_start():
    up = [10.0 + i for i in range(40)]
    panel = _panel({"AAA": up, "BBB": up, "SPY": [100.0] * 40})
    row = {"member_id": "m1", "member": "M", "chamber": "house", "party": "", "state": "", "amount": 10_000}
    trades = pd.DataFrame([
        {**row, "ticker": "AAA", "tx_type": "P", "traded": SESSIONS[0], "disclosed": SESSIONS[0]},   # still held
        {**row, "ticker": "BBB", "tx_type": "P", "traded": SESSIONS[0], "disclosed": SESSIONS[0]},
        {**row, "ticker": "BBB", "tx_type": "S", "traded": SESSIONS[4], "disclosed": SESSIONS[4]},   # sold before
    ])
    data = congress.build(trades, panel, _history(["AAA", "BBB", "SPY"]))
    as_of = 35
    window_days = (SESSIONS[as_of] - SESSIONS[20]).days                  # window starts at session 20
    lots = congress.lot_returns(data, as_of, window_days)
    assert list(lots["ticker"]) == ["AAA"]                               # the sold lot is out
    lot = lots.iloc[0]
    assert lot["carried"] and lot["start"] == 20 and lot["open"]
    assert np.isclose(lot["ret"], up[as_of] / up[20] - 1)                # return from the window start
    assert np.isclose(lot["value"], 10_000 * up[20] / up[1])             # valued at the window start


# ------------------------------------------------------------------ 13F

def test_parse_form_idx_keeps_only_holdings_reports():
    text = "\n".join([
        "Form Type   Company Name                CIK         Date Filed  File Name",
        "13F-HR      SOME CAPITAL LLC            1234567     20260814    edgar/data/1234567/0001-26-000001.txt",
        "13F-HR/A    OTHER LP                    7654321     20260814    edgar/data/7654321/0001-26-000002.txt",
        "13F-NT      NOTICE FILER                1111111     20260814    edgar/data/1111111/0001-26-000003.txt",
    ])
    assert parse_form_idx(text) == [("13F-HR", 1234567, "20260814"), ("13F-HR/A", 7654321, "20260814")]


def test_rank_funds_uses_only_completed_periods_and_gates():
    b = hedge.Books(
        primary=pd.DataFrame({"filing": [1, 2], "cik": [10, 20], "name": ["Good", "Small"],
                              "filing_date": pd.to_datetime(["2026-05-14", "2026-05-14"]),
                              "report_date": pd.to_datetime(["2026-03-31", "2026-03-31"]),
                              "gated": [True, False], "book": [5e8, 5e7], "n": [40, 40]}),
        positions=pd.DataFrame(columns=["filing", "ticker", "value", "weight"]))
    entries = pd.to_datetime(["2025-08-15", "2025-11-15", "2026-02-15", "2026-05-15"])
    periods = pd.DataFrame([{"cik": c, "entry": e, "exit": e + pd.Timedelta(days=91), "ret": 0.10, "spy_ret": 0.02,
                             "coverage": 0.95, "book": 5e8} for c in (10, 20) for e in entries])
    before_last = hedge.rank_funds(periods, b, pd.Timestamp("2026-06-01"))
    assert list(before_last.index) == [10] and before_last.loc[10, "periods"] == 3     # 4th period still open
    assert 20 not in before_last.index                                                   # gated out (book < $100M)
