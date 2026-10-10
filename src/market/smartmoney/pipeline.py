"""Daily smart-money steps: fund periods, the names we need prices for, and the leaderboards.

  periods   price any 13F holding period completed since the last run (hedge.sync_periods)
  signals   register every Congress-bought name and every name near the top of a 13F signal as
            a tracked security, then fetch its history (security master → bars → splits/dividends)
  leaders   point-in-time top-50 Congress members and 13F funds per report date (entity_scores)
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from market.data import bars, corpactions, securities
from market.reports.snapshot import report_dates
from market.smartmoney import congress, hedge, ledgers
from market.smartmoney.signals import SmartMoney
from market.store.db import connect, log_fetch, replace_rows
from market.store.panel import load_panel

CANDIDATES = 30                   # names per signal per date that must be priceable
LEADERS = 50
SCAN_SOURCE = "smartmoney_scan"


def _scan_start(con, full: bool) -> date:
    row = con.execute("SELECT max(key) FROM fetch_log WHERE source = ?", [SCAN_SOURCE]).fetchone()
    if full or not row or not row[0]:
        return congress.SIGNAL_START.date() - timedelta(days=7)
    return date.fromisoformat(row[0]) - timedelta(days=7)


def _report_sessions(panel, start: date) -> list[tuple[date, pd.Timestamp]]:
    out = []
    for d in report_dates(start, date.today() + timedelta(days=4)):
        as_of = panel.session_on_or_before(d - timedelta(days=1))
        if as_of is not None and as_of.date() < d:
            out.append((d, as_of))
    return out


def signals(full: bool = False) -> dict:
    con = connect()
    added = {"congress": securities.set_signal_tickers(con, "congress", congress.first_needed(ledgers.congress_frame()))}
    start = _scan_start(con, full)
    con.close()

    hs = hedge.load_signals()
    con = connect()
    sessions = sorted({a for _, a in _report_sessions(load_panel_sessions(con), start)})
    first: dict[str, date] = {}
    for as_of in sessions:
        for frame in (hs.new_buys(as_of), hs.drivers(as_of)):
            for ticker in list(frame.index[:CANDIDATES]):
                first.setdefault(ticker, as_of.date())
    added["hedge"] = securities.set_signal_tickers(con, "hedge", first)
    con.close()
    return {"new_signal_tickers": added, "securities": securities.extend(),
            "bars": bars.backfill_new_securities(), "corpactions": corpactions.sync_new_tickers(),
            "gaps": bars.repair_gaps()}


class _Sessions:
    """Just enough of a Panel (session_on_or_before) from the calendar, without loading prices."""

    def __init__(self, days: list[date]):
        self.sessions = pd.DatetimeIndex(pd.to_datetime(days))

    def session_on_or_before(self, d: date):
        i = self.sessions.searchsorted(pd.Timestamp(d), side="right") - 1
        return self.sessions[i] if i >= 0 else None


def load_panel_sessions(con) -> _Sessions:
    return _Sessions([d for (d,) in con.execute("SELECT date FROM calendar WHERE is_open ORDER BY date").fetchall()])


def leaders(full: bool = False) -> dict:
    con = connect()
    start = _scan_start(con, full)
    panel = load_panel(con)
    sm = SmartMoney(con, panel)
    con.close()
    rows = []
    dates = _report_sessions(panel, start)
    disclosed = ledgers.congress_frame()
    for report_date, as_of in dates:
        scores = sm.congress.scores(as_of)
        if len(scores):
            ranked = scores.dropna(subset=["rank"]).head(LEADERS)
            totals = congress.disclosure_totals(disclosed, as_of).reindex(ranked.index).fillna(0)
            for member_id, r in ranked.iterrows():
                rows.append({"kind": "congress", "report_date": report_date, "entity_id": member_id,
                             "name": r["member"], "rank": int(r["rank"]), "score": float(r["dw_alpha"]),
                             "features": json.dumps({"chamber": r["chamber"], "party": r.get("party"),
                                                     "state": r.get("state"), "lots": int(r["lots"]),
                                                     "open_lots": int(r["open_lots"]), "carried": int(r["carried"]),
                                                     "dollars": float(r["dollars"]),
                                                     "trades": int(totals.at[member_id, "trades"]),
                                                     "bought": float(totals.at[member_id, "bought"]),
                                                     "sold": float(totals.at[member_id, "sold"]),
                                                     "disclosed": float(totals.at[member_id, "bought"] + totals.at[member_id, "sold"]),
                                                     "return": float(r["dw_return"]), "beat_spy": float(r["beat_spy"])})})
        funds = sm.hedge.ranked(as_of)
        for cik, r in funds.head(LEADERS).iterrows():
            rows.append({"kind": "hedge", "report_date": report_date, "entity_id": str(cik), "name": r["name"],
                         "rank": int(r["rank"]), "score": float(r["alpha"]),
                         "features": json.dumps({"periods": int(r["periods"]), "return": float(r["fund_return"]),
                                                 "spy_return": float(r["spy_return"]), "hit_rate": float(r["hit_rate"]),
                                                 "coverage": float(r["coverage"]), "book": float(r["book"]),
                                                 "last_filed": str(r["filing_date"].date()),
                                                 "ranked_funds": len(funds)})})
    con = connect()
    if dates:
        replace_rows(con, "entity_scores", pd.DataFrame(rows, columns=["kind", "report_date", "entity_id", "name", "rank", "score", "features"]), "report_date >= ?", [dates[0][0]])
        log_fetch(con, SCAN_SOURCE, str(dates[-1][0]), len(rows), immutable=False)
    con.close()
    return {"report_dates": len(dates), "rows": len(rows)}
