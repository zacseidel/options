import pandas as pd
import pytest

from market.data.dividend_signals import events


def _div(rows):
    return pd.DataFrame(rows, columns=["security_id", "ex_date", "declared", "amount", "kind", "frequency"])


def test_raise_cut_and_announcement_date():
    div = _div([
        ("A", "2024-02-10", "2024-01-25", 1.00, "CD", 4),
        ("A", "2024-05-10", "2024-04-25", 1.12, "CD", 4),      # +12%, dated by the declaration
        ("A", "2024-08-10", None, 1.00, "CD", 4),              # cut, no declaration → ex-date
        ("A", "2024-09-01", "2024-08-20", 2.00, "SC", 0),      # special
    ])
    ev = events(div, pd.DataFrame(columns=["security_id", "ex_date"]), pd.Timestamp("2020-01-01"))
    raise_ = ev[ev["type"] == "raise"].iloc[0]
    assert raise_["change"] == pytest.approx(0.12) and raise_["date"] == pd.Timestamp("2024-04-25")
    cut = ev[ev["type"] == "cut"].iloc[0]
    assert cut["date"] == pd.Timestamp("2024-08-10") and cut["change"] == pytest.approx(1 / 1.12 - 1)
    assert (ev["type"] == "special").sum() == 1
    assert (ev["type"] == "initiation").sum() == 1                # the first dividend, with history before it


def test_split_or_frequency_change_is_not_a_raise():
    div = _div([
        ("B", "2024-02-10", "2024-01-25", 1.00, "CD", 4),
        ("B", "2024-05-10", "2024-04-25", 0.50, "CD", 4),      # 2-for-1 split in between
        ("B", "2024-08-10", "2024-07-25", 1.00, "CD", 2),      # switched to semiannual
    ])
    splits = pd.DataFrame({"security_id": ["B"], "ex_date": ["2024-03-01"]})
    ev = events(div, splits, pd.Timestamp("2024-01-01"))
    assert not ev["type"].isin(["raise", "cut"]).any()
    assert (ev["type"] == "initiation").sum() == 0                # history too short to call it one
