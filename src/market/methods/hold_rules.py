"""Hold rules: category snapshots → exposure windows (trades) for one strategy.

Conventions (PLAN §2.3, carried over from the eval repo):
  * A report is published before the open on its report date; entries and report-driven
    exits execute at the first session on or after the report date.
  * Price-indicator exits are decided on a completed close and execute the next session.
  * Fills use the session VWAP (split-adjusted), falling back to mid(open, close).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from market.store.panel import Panel


@dataclass
class Trade:
    security_id: str
    ticker: str
    signal_date: date
    entry_session: pd.Timestamp
    exit_signal_date: date | None = None
    exit_session: pd.Timestamp | None = None
    exit_reason: str | None = None
    lot: int = 0
    extra: dict = field(default_factory=dict)


def fill_price(panel: Panel, session: pd.Timestamp, security_id: str) -> float:
    vwap = panel.vwap.at[session, security_id]
    if pd.notna(vwap) and vwap > 0:
        return float(vwap)
    o, c = panel.open.at[session, security_id], panel.close.at[session, security_id]
    return float((o + c) / 2) if pd.notna(o) and pd.notna(c) else float(c)


def _traded_on_or_after(panel: Panel, security_id: str, when: date) -> pd.Timestamp | None:
    """First session on/after `when` with a bar for the security (skips halts)."""
    closes = panel.close[security_id]
    after = closes.loc[pd.Timestamp(when):].dropna()
    return after.index[0] if len(after) else None


def selected(snapshots: pd.DataFrame, slot) -> dict[date, pd.DataFrame]:
    """report_date → rows inside the slot ([lo, hi] ranks, or 'all')."""
    rows = snapshots if slot == "all" else snapshots[snapshots["rank"].between(slot[0], slot[1])]
    return {d: g for d, g in rows.groupby("report_date")}


def report_dates(snapshots: pd.DataFrame) -> list[date]:
    return sorted(snapshots["report_date"].unique())


def while_listed(snapshots: pd.DataFrame, panel: Panel, slot, params: dict) -> list[Trade]:
    picks = selected(snapshots, slot)
    trades, open_by_id = [], {}
    for report_date in report_dates(snapshots):
        today = picks.get(report_date, pd.DataFrame(columns=["security_id", "ticker"]))
        listed = dict(zip(today["security_id"], today["ticker"]))
        for sid in sorted(set(open_by_id) - set(listed)):
            trade = open_by_id.pop(sid)
            exit_session = _traded_on_or_after(panel, sid, report_date)
            trade.exit_signal_date, trade.exit_session = report_date, exit_session
            trade.exit_reason = "dropped from slot" if exit_session is not None else "exit pending (next session)"
            trades.append(trade)
        for sid, ticker in sorted(listed.items()):
            if sid in open_by_id:
                continue
            entry = _traded_on_or_after(panel, sid, report_date)
            if entry is not None:
                open_by_id[sid] = Trade(sid, ticker, report_date, entry)
    return trades + list(open_by_id.values())


def fixed_hold(snapshots: pd.DataFrame, panel: Panel, slot, params: dict) -> list[Trade]:
    sessions = params["sessions"]
    trades = []
    for report_date, rows in sorted(selected(snapshots, slot).items()):
        for sid, ticker in zip(rows["security_id"], rows["ticker"]):
            entry = _traded_on_or_after(panel, sid, report_date)
            if entry is None:
                continue
            pos = panel.sessions.get_loc(entry) + sessions
            trade = Trade(sid, ticker, report_date, entry, lot=len(trades))
            if pos < len(panel.sessions):
                trade.exit_session = panel.sessions[pos]
                trade.exit_reason = f"held {sessions} sessions"
            trades.append(trade)
    return trades


def indicator(close: pd.Series, kind: str, window: int) -> pd.Series:
    if kind == "ema":
        return close.ewm(span=window, adjust=False, min_periods=window).mean()
    if kind == "sma":
        return close.rolling(window, min_periods=window).mean()
    raise ValueError(f"unknown indicator {kind}")


def price_exit(snapshots: pd.DataFrame, panel: Panel, slot, params: dict) -> list[Trade]:
    kind, window, when = params["indicator"], params["window"], params.get("exit_when", "below")
    picks = selected(snapshots, slot)
    trades = []
    signals_by_id: dict[str, list[tuple[date, str]]] = {}
    for report_date, rows in picks.items():
        for sid, ticker in zip(rows["security_id"], rows["ticker"]):
            signals_by_id.setdefault(sid, []).append((report_date, ticker))

    for sid, signals in signals_by_id.items():
        close = panel.close[sid]
        level = indicator(close.dropna(), kind, window).reindex(close.index)
        crossed = (close < level) if when == "below" else (close > level)
        busy_until: pd.Timestamp | None = None
        for report_date, ticker in sorted(signals):
            entry = _traded_on_or_after(panel, sid, report_date)
            if entry is None or (busy_until is not None and entry <= busy_until):
                continue                                   # still holding (or selling that session)
            trade = Trade(sid, ticker, report_date, entry)
            after = crossed.loc[entry:]
            hits = after[after.fillna(False)].index
            if len(hits):
                signal_session = hits[0]
                nxt = close.loc[signal_session:].dropna().index
                if len(nxt) > 1:
                    trade.exit_signal_date = signal_session.date()
                    trade.exit_session = nxt[1]
                    trade.exit_reason = f"close {when} {kind.upper()}{window}"
                    trade.extra = {"exit_signal_close": float(close[signal_session]),
                                   "exit_signal_level": float(level[signal_session])}
            trades.append(trade)
            busy_until = trade.exit_session if trade.exit_session is not None else panel.sessions[-1]
    return trades


HOLD_RULES = {"while_listed": while_listed, "fixed_hold": fixed_hold, "price_exit": price_exit}
