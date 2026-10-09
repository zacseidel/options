from datetime import date

import pandas as pd

from market.data.universe_wiki import clean_ticker, members_on, replay


def changes(rows):
    return pd.DataFrame(rows, columns=["date", "action", "ticker"])


def test_replay_recovers_membership_on_past_dates():
    # Today: {A, B, D}. On 2024-06-01 D replaced C; on 2023-01-01 B replaced X.
    log = changes([
        (date(2024, 6, 1), "add", "D"), (date(2024, 6, 1), "drop", "C"),
        (date(2023, 1, 1), "add", "B"), (date(2023, 1, 1), "drop", "X"),
    ])
    result = replay({"A", "B", "D"}, log)
    assert result.anomalies == []
    assert members_on(result.intervals, date(2025, 1, 1)) == {"A", "B", "D"}
    assert members_on(result.intervals, date(2024, 6, 1)) == {"A", "B", "D"}   # effective date inclusive
    assert members_on(result.intervals, date(2024, 5, 31)) == {"A", "B", "C"}
    assert members_on(result.intervals, date(2022, 12, 31)) == {"A", "C", "X"}


def test_readded_ticker_gets_two_intervals():
    log = changes([
        (date(2025, 3, 1), "add", "R"),
        (date(2023, 3, 1), "drop", "R"),
        (date(2021, 3, 1), "add", "R"),
    ])
    result = replay({"R"}, log)
    rows = result.intervals[result.intervals["ticker"] == "R"]
    assert len(rows) == 2
    assert not members_on(result.intervals, date(2024, 1, 1))
    assert members_on(result.intervals, date(2022, 1, 1)) == {"R"}
    assert members_on(result.intervals, date(2020, 1, 1)) == set()


def test_inconsistent_events_are_reported_not_fatal():
    # META is current; Wikipedia recorded the 2013 addition under the old ticker FB.
    log = changes([(date(2013, 12, 23), "add", "FB")])
    result = replay({"META"}, log)
    assert result.anomalies == [{"date": date(2013, 12, 23), "ticker": "FB", "issue": "added but not a member afterwards"}]
    assert members_on(result.intervals, date(2010, 1, 1)) == {"META"}   # resolved later via ticker_history


def test_clean_ticker_strips_footnotes():
    assert clean_ticker(" brk.b[4] ") == "BRK.B"
    assert clean_ticker(float("nan")) is None
