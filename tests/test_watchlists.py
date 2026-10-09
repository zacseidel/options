from datetime import date

from market.data import watchlists
from market.store.db import connect

FILE_V1 = """
watchlists:
  space:
    options: true
    tickers:
      - RKLB: 2026-01-05
      - asts
  income:
    tickers: [SCHD]
"""

FILE_V2 = """
watchlists:
  space:
    options: true
    tickers:
      - RKLB: 2026-01-05
      - JOBY: 2026-06-01
"""


def test_load_parses_dated_and_plain_entries():
    lists = {wl.name: wl for wl in watchlists.load(FILE_V1)}
    assert lists["space"].tickers == {"RKLB": date(2026, 1, 5), "ASTS": None}
    assert lists["space"].options and not lists["income"].options
    assert watchlists.option_tickers(list(lists.values())) == {"RKLB", "ASTS"}


def test_sync_keeps_history_when_names_or_lists_are_removed():
    con = connect(":memory:")
    watchlists.sync(con, watchlists.load(FILE_V1), today=date(2026, 3, 1))
    assert set(watchlists.members(con, "watchlist:space", date(2026, 2, 1))["ticker"]) == {"RKLB", "ASTS"}
    assert set(watchlists.members(con, "watchlist:space", date(2025, 12, 1))["ticker"]) == {"ASTS"}  # RKLB not yet added

    report = watchlists.sync(con, watchlists.load(FILE_V2), today=date(2026, 7, 1))
    assert report["space"] == {"added": ["JOBY"], "removed": ["ASTS"], "members": 2, "options": True}
    assert report["income"] == {"deleted": True}
    # ASTS was a member until the sync that removed it; the income list survives in history.
    assert set(watchlists.members(con, "watchlist:space", date(2026, 6, 30))["ticker"]) == {"RKLB", "ASTS", "JOBY"}
    assert set(watchlists.members(con, "watchlist:space", date(2026, 7, 1))["ticker"]) == {"RKLB", "JOBY"}
    assert set(watchlists.members(con, "watchlists", date(2026, 5, 1))["ticker"]) == {"RKLB", "ASTS", "SCHD"}
    assert watchlists.members(con, "watchlist:income", date(2026, 8, 1)).empty


def test_resync_is_idempotent():
    con = connect(":memory:")
    lists = watchlists.load(FILE_V1)
    watchlists.sync(con, lists, today=date(2026, 3, 1))
    report = watchlists.sync(con, lists, today=date(2026, 3, 2))
    assert report["space"]["added"] == [] and report["space"]["removed"] == []
    assert con.execute("SELECT count(*) FROM universe_membership").fetchone()[0] == 3
