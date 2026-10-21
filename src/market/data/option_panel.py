"""Option panel sync: stream OPRA day-aggregate flat files into `option_bars` (PLAN §4).

Options are kept only for the select option set (decision D8), and only for the sessions
around the periods a name is held:
  * names entering the strategy slots in `options.underlyings.category_slots` — from
    `pad_before_days` before each window's entry to `pad_after_days` after its exit
    (open windows run to today);
  * names on watchlists flagged `options: true` — from the date they were added.

Coverage is tracked per (session, root) in `option_coverage`, so a name that joins the set
later costs one batched re-stream of just the sessions it needs, and a file is never read
twice for the same root. Flat files are streamed and discarded (nothing raw is stored).

The same pass summarizes each file for every security we price into `option_flow_daily`
(`market.data.option_flow`); sessions missing a summary are streamed for it alone.

Usage:  python -m market.data.option_panel [--dry-run]
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
from botocore.exceptions import ClientError

from market.config import config
from market.data import flatfiles, option_flow, watchlists
from market.data.options import filter_panel, option_root
from market.evaluate.engine import load_strategies
from market.methods.hold_rules import HOLD_RULES
from market.store.db import connect, transaction
from market.store.panel import Panel, load_panel


def history_start(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=config()["options"]["panel"]["history_days"])


def option_windows(con, panel: Panel, today: date | None = None) -> pd.DataFrame:
    """security_id, root, start, end — the date ranges whose option rows we keep."""
    cfg = config()["options"]
    pad_before = timedelta(days=cfg["panel"]["pad_before_days"])
    pad_after = timedelta(days=cfg["panel"]["pad_after_days"])
    today = today or date.today()
    rows = []
    wanted = set(cfg["underlyings"]["category_slots"])
    for strat in load_strategies():
        if strat.id not in wanted or strat.instrument != "stock":
            continue
        snaps = con.execute(
            "SELECT report_date, security_id, ticker, rank FROM category_snapshots "
            "WHERE category_id = ? AND origin = 'backtest' ORDER BY report_date, rank", [strat.category]
        ).df()
        snaps["report_date"] = pd.to_datetime(snaps["report_date"]).dt.date
        for t in HOLD_RULES[strat.hold](snaps, panel, strat.slot, strat.params):
            end = t.exit_session.date() + pad_after if t.exit_session is not None else today
            rows.append((t.security_id, option_root(t.ticker), t.entry_session.date() - pad_before, end))
    if cfg["underlyings"].get("watchlists"):
        ids = dict(con.execute("SELECT ticker, security_id FROM securities").fetchall())
        for wl in watchlists.load():
            if not wl.options:
                continue
            for ticker, added in wl.tickers.items():
                if ticker in ids:
                    rows.append((ids[ticker], option_root(ticker), added or history_start(today), today))
    frame = pd.DataFrame(rows, columns=["security_id", "root", "start", "end"])
    cap = cfg["underlyings"]["max_underlyings"]
    if frame["security_id"].nunique() > cap:
        raise RuntimeError(f"option set has {frame['security_id'].nunique()} underlyings, over the cap of {cap}")
    return frame


def needed_by_session(windows: pd.DataFrame, sessions: pd.DatetimeIndex, start: date) -> dict[date, dict[str, str]]:
    """session → {root: security_id} for every session inside a window (on/after `start`)."""
    out: dict[date, dict[str, str]] = {}
    days = [s.date() for s in sessions if s.date() >= start]
    for sid, root, lo, hi in windows.itertuples(index=False):
        for d in days:
            if lo <= d <= hi:
                out.setdefault(d, {})[root] = sid
    return out


# Before a session's file is published (~11:00 ET next day) the bucket can answer 403 rather
# than NoSuchKey; within this many calendar days of `today` a 403 means "not published yet".
RECENT_403_DAYS = 4


def _unpublished(exc: ClientError, session: date, today: date) -> bool:
    code = exc.response.get("Error", {}).get("Code")
    if code in ("NoSuchKey", "404"):
        return True
    return code in ("403", "AccessDenied", "Forbidden") and (today - session).days <= RECENT_403_DAYS


def flow_roots(history: pd.DataFrame, panel: Panel, session: date) -> dict[str, tuple[str, float]]:
    """OCC root → (security_id, unadjusted close) for every security priced on `session`."""
    when = pd.Timestamp(session)
    live = history[(history["valid_from"] <= when) & (history["valid_to"] > when)].sort_values("priority")
    live = live.drop_duplicates("security_id").drop_duplicates("ticker")
    closes = panel.raw_close.loc[when]
    out = {}
    for sid, ticker in zip(live["security_id"], live["ticker"]):
        px = closes.get(sid)
        if px is not None and pd.notna(px) and px > 0:
            out.setdefault(option_root(ticker), (sid, float(px)))
    return out


def _stream(session: date, roots: dict[str, str], spot: dict[str, float], bands: dict, today: date,
            flow: dict[str, tuple[str, float]] | None, rate: float):
    try:
        rows, size = flatfiles.read_day("options_day", session)
    except ClientError as exc:
        if _unpublished(exc, session, today):
            return session, None, None, 0
        raise
    spot_by_root = {root: spot[root] for root in roots if root in spot}
    frame = filter_panel(rows, session, spot_by_root, bands) if roots else None
    summary = option_flow.summarize(rows, session, flow, rate) if flow is not None else None
    return session, frame, summary, size


def sync(dry_run: bool = False, today: date | None = None, flow_only: bool = False) -> dict:
    """Stream the sessions the panel or the flow summary still needs; `flow_only` skips the panel
    (the daily run summarizes flow before categories, then fills the panel after them)."""
    t0 = time.time()
    con = connect()
    panel = load_panel(con)
    windows = option_windows(con, panel, today)
    start = max(history_start(today), panel.sessions[0].date())
    need = needed_by_session(windows, panel.sessions, start)
    covered = con.execute("SELECT session, root FROM option_coverage").fetchall()
    have: dict[date, set[str]] = {}
    for d, root in covered:
        have.setdefault(d, set()).add(root)
    todo = {d: {r: sid for r, sid in roots.items() if r not in have.get(d, set())} for d, roots in need.items()}
    todo = {d: roots for d, roots in todo.items() if roots and not flow_only}
    flow_done = {r[0] for r in con.execute("SELECT session FROM option_flow_sessions").fetchall()}
    flow_todo = {s.date() for s in panel.sessions if s.date() >= start and s.date() not in flow_done}
    stream = sorted(set(todo) | flow_todo)
    stats = {"underlyings": int(windows["security_id"].nunique()), "sessions_needed": len(need),
             "sessions_to_stream": len(stream), "root_sessions": sum(len(r) for r in todo.values()),
             "flow_sessions": len(flow_todo)}
    if dry_run or not stream:
        con.close()
        return {**stats, "seconds": round(time.time() - t0, 1)}
    history = con.execute("SELECT security_id, ticker, valid_from, valid_to, priority FROM ticker_history").df()
    history["valid_from"] = pd.to_datetime(history["valid_from"])
    history["valid_to"] = pd.to_datetime(history["valid_to"]).fillna(pd.Timestamp.max)
    rate = config()["evaluation"]["risk_free_rate"]

    bands = config()["options"]["panel"]
    rows_in, flow_rows, bytes_in, missing = 0, 0, 0, []
    with ThreadPoolExecutor(max_workers=bands.get("workers", 4)) as pool:
        futures = []
        for d in stream:
            ts = pd.Timestamp(d)
            roots = todo.get(d, {})
            spot = {root: float(panel.raw_close.at[ts, sid]) for root, sid in roots.items()
                    if sid in panel.raw_close.columns and pd.notna(panel.raw_close.at[ts, sid])}
            flow = flow_roots(history, panel, d) if d in flow_todo else None
            futures.append(pool.submit(_stream, d, roots, spot, bands, today or date.today(), flow, rate))
        for done, future in enumerate(as_completed(futures), 1):
            session, frame, summary, size = future.result()
            if frame is None and summary is None:  # not published yet (or outside the plan window)
                missing.append(str(session))
                continue
            roots = todo.get(session, {})
            with transaction(con):
                if frame is not None:
                    counts = frame.groupby("root").size().reindex(list(roots), fill_value=0)
                    con.execute(f"DELETE FROM option_bars WHERE session = ? AND root IN ({','.join('?' * len(roots))})",
                                [session, *roots])
                    if not frame.empty:
                        con.register("_bars", frame)
                        con.execute("INSERT INTO option_bars SELECT session, root, expiry, kind, strike, open, close, "
                                    "volume, transactions FROM _bars")
                        con.unregister("_bars")
                    con.executemany("INSERT OR REPLACE INTO option_coverage VALUES (?, ?, ?)",
                                    [[session, root, int(n)] for root, n in counts.items()])
                    rows_in += len(frame)
                if summary is not None:
                    con.execute("DELETE FROM option_flow_daily WHERE session = ?", [session])
                    con.register("_flow", summary)
                    con.execute(f"INSERT INTO option_flow_daily SELECT {', '.join(option_flow.FLOW_COLUMNS)} FROM _flow")
                    con.unregister("_flow")
                    con.execute("INSERT OR REPLACE INTO option_flow_sessions VALUES (?, ?, ?)",
                                [session, len(summary), pd.Timestamp.now()])
                    flow_rows += len(summary)
            bytes_in += size
            if done % 25 == 0:
                print(f"  options: {done}/{len(futures)} files, {rows_in:,} rows, {bytes_in / 1e9:.2f} GB", flush=True)
    con.close()
    return {**stats, "rows": rows_in, "flow_rows": flow_rows, "gb_streamed": round(bytes_in / 1e9, 2),
            "unpublished": missing[-5:], "seconds": round(time.time() - t0, 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(sync(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
