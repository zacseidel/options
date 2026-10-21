from datetime import date, datetime

from market.data.earnings import _eastern, parse_filings


def test_edgar_acceptance_time_to_eastern():
    # Checked against EDGAR filing index pages. Apple's JSON times are shifted; others are true UTC.
    assert _eastern("2026-07-31T00:30:28.000Z", date(2026, 7, 30)) == datetime(2026, 7, 30, 16, 30, 28)
    assert _eastern("2026-02-27T02:08:12.000Z", date(2026, 2, 26)) == datetime(2026, 2, 26, 16, 8, 12)
    assert _eastern("2026-07-22T11:31:32.000Z", date(2026, 7, 22)) == datetime(2026, 7, 22, 7, 31, 32)
    assert _eastern("2026-07-22T20:10:15.000Z", date(2026, 7, 22)) == datetime(2026, 7, 22, 16, 10, 15)
    # A shifted pre-market release stays 4 h late (07:00 → 11:00) but reacts in the same session.
    assert _eastern("2026-07-30T15:00:17.000Z", date(2026, 7, 30)) == datetime(2026, 7, 30, 11, 0, 17)


def test_only_item_202_eightks_after_the_start():
    block = {"form": ["8-K", "8-K", "10-Q", "8-K"], "items": ["2.02,9.01", "5.02", "", "2.02"],
             "accessionNumber": ["a", "b", "c", "d"], "filingDate": ["2026-07-30", "2026-07-01", "2026-07-31", "2019-01-30"],
             "acceptanceDateTime": ["2026-07-31T00:30:28.000Z"] * 4}
    rows = parse_filings(1, block)
    assert [r[1] for r in rows] == ["a"] and rows[0][2] == date(2026, 7, 30)


def test_reaction_session_by_acceptance_time():
    import pandas as pd
    from market.data.earnings_signals import reaction_session
    from market.store.panel import Panel
    idx = pd.bdate_range("2026-07-27", periods=10)            # Mon 07-27 … Fri 08-07
    close = pd.DataFrame({"A": range(10)}, index=idx, dtype=float)
    ones = close * 0 + 1
    panel = Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                  volume=ones, tr=close, split_factor=ones)
    T = pd.Timestamp
    assert reaction_session(panel, T("2026-07-30 16:30")) == T("2026-07-31")   # after the close → next session
    assert reaction_session(panel, T("2026-07-30 06:30")) == T("2026-07-30")   # pre-market → same session
    assert reaction_session(panel, T("2026-07-30 12:00")) == T("2026-07-30")   # during the session
    assert reaction_session(panel, T("2026-08-01 09:00")) == T("2026-08-03")   # Saturday → Monday
