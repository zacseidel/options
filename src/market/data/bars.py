"""Daily bars for the tracked set via grouped daily (one call per session for the whole market).

Each response is reduced to tracked securities before storage (~1,150 of ~12,500 tickers),
mapped by ticker *as of that session* so renames and reused tickers land on the right id.
Bars are unadjusted; adjustment happens on read. Weekdays with no data become holidays in
`calendar`. Completed sessions are logged immutable and never fetched again.

Usage:  python -m market.data.bars [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from market.data.polygon import NotEntitled, Polygon, PolygonError
from market.data.securities import history_start, ticker_map, ticker_priorities_on, tickers_on
from market.store.db import already_fetched, connect, log_fetch, transaction

SOURCE = "grouped_daily"
CHUNK = 40
NEW_YORK = ZoneInfo("America/New_York")
SESSION_FINAL_HOUR = 17          # ET: the close plus the 15-minute delay, with margin


def last_final_session_day(now: datetime | None = None) -> date:
    """Latest calendar day whose session is final. On a delayed plan the grouped endpoint
    serves a partial bar for today during market hours, so today counts only after 17:00 ET."""
    now = (now or datetime.now(tz=NEW_YORK)).astimezone(NEW_YORK)
    return now.date() if now.hour >= SESSION_FINAL_HOUR else now.date() - timedelta(days=1)


def weekdays(start: date, end: date) -> list[date]:
    return [d.date() for d in pd.bdate_range(start, end)]


async def _fetch(poly: Polygon, session: date) -> tuple[date, list[dict] | None]:
    """Rows for a session; [] for a holiday; None when not yet published (today, pre-close)."""
    try:
        body = await poly.get(f"/v2/aggs/grouped/locale/us/market/stocks/{session}", {"adjusted": "false"})
    except NotEntitled as exc:
        if "before end of day" in exc.message:
            return session, None
        raise
    rows = body.get("results") or []
    if not rows and session >= last_final_session_day():
        return session, None              # not published yet — never record it as a holiday
    return session, rows


def _to_frame(rows: list[dict], session: date, mapping: dict[str, str],
              priority: dict[str, int] | None = None) -> pd.DataFrame:
    """Keep tracked tickers; when two tickers map to one security (an alias and the real
    ticker), the better-priority ticker's bar wins."""
    priority = priority or {}
    kept = sorted((r for r in rows if r.get("T") in mapping and r.get("c") is not None),
                  key=lambda r: priority.get(r["T"], 9))
    return pd.DataFrame({
        "security_id": [mapping[r["T"]] for r in kept],
        "date": session,
        "open": [r.get("o") for r in kept],
        "high": [r.get("h") for r in kept],
        "low": [r.get("l") for r in kept],
        "close": [r["c"] for r in kept],
        "volume": [r.get("v") for r in kept],
        "vwap": [r.get("vw") for r in kept],
    }).drop_duplicates("security_id")


def backfill(start: date | None = None, end: date | None = None) -> dict:
    con = connect()
    start = start or history_start()
    end = min(end or date.today(), last_final_session_day())
    pending = [d for d in weekdays(start, end) if not already_fetched(con, SOURCE, str(d))]
    history = ticker_map(con)
    stats = {"pending": len(pending), "sessions": 0, "holidays": 0, "unpublished": 0, "rows": 0, "calls": 0}

    async def run() -> None:
        async with Polygon() as poly:
            for i in range(0, len(pending), CHUNK):
                results = await asyncio.gather(*(_fetch(poly, d) for d in pending[i:i + CHUNK]))
                with transaction(con):
                    for session, rows in results:
                        if rows is None:
                            stats["unpublished"] += 1
                            continue
                        if not rows:
                            con.execute("INSERT OR REPLACE INTO calendar VALUES (?, FALSE, FALSE)", [session])
                            stats["holidays"] += 1
                        else:
                            frame = _to_frame(rows, session, tickers_on(history, session),
                                              ticker_priorities_on(history, session))
                            con.execute("DELETE FROM bars_daily WHERE date = ?", [session])
                            con.register("_bars", frame)
                            con.execute("INSERT INTO bars_daily SELECT * FROM _bars")
                            con.unregister("_bars")
                            con.execute("INSERT OR REPLACE INTO calendar VALUES (?, TRUE, FALSE)", [session])
                            stats["sessions"] += 1
                            stats["rows"] += len(frame)
                        log_fetch(con, SOURCE, str(session), len(rows), immutable=True)
                done = min(i + CHUNK, len(pending))
                print(f"   {done}/{len(pending)} sessions ({stats['rows']:,} rows)", flush=True)
            stats["calls"] = poly.calls

    try:
        asyncio.run(run())
    finally:
        con.close()
    return stats


TICKER_SOURCE = "bars_ticker"


async def _ticker_range(poly: Polygon, ticker: str, start: date, end: date) -> list[dict]:
    try:
        body = await poly.get(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                              {"adjusted": "false", "sort": "asc", "limit": 50000})
    except PolygonError:
        return []
    return body.get("results") or []


def backfill_new_securities() -> dict:
    """History for securities that joined the tracked set after their sessions were fetched.

    Grouped daily only stores what was tracked on the day it was fetched, so a name added later
    (a new Congress or 13F signal, a watchlist addition) gets its past bars here: one range call
    per ticker it used, from its first needed date. Afterwards the daily grouped fetch covers it.
    """
    con = connect()
    last = con.execute("SELECT max(date) FROM calendar WHERE is_open").fetchone()[0]
    todo = con.execute(f"""
        WITH needed AS (
            SELECT h.security_id, h.ticker, h.valid_from, h.valid_to,
                   min(coalesce(m.valid_from, DATE '1900-01-01')) AS first_needed
            FROM ticker_history h
            JOIN universe_membership m ON m.ticker = h.ticker
            GROUP BY ALL
        )
        SELECT n.* FROM needed n
        WHERE n.security_id NOT IN (SELECT DISTINCT security_id FROM bars_daily)
          AND n.security_id NOT IN (SELECT key FROM fetch_log WHERE source = '{TICKER_SOURCE}')
    """).df()
    if todo.empty or last is None:
        con.close()
        return {"securities": 0}
    floor = pd.Timestamp(history_start())
    jobs = []
    for row in todo.itertuples():
        start = max(floor, pd.Timestamp(row.first_needed), pd.Timestamp(row.valid_from)).date()
        end = min(pd.Timestamp(last), pd.Timestamp(row.valid_to) - pd.Timedelta(days=1)
                  if pd.notna(row.valid_to) else pd.Timestamp(last)).date()
        if start <= end:
            jobs.append((row.security_id, row.ticker, start, end))

    async def run() -> tuple[list, int]:
        async with Polygon() as poly:
            got = await asyncio.gather(*(_ticker_range(poly, t, s, e) for _, t, s, e in jobs))
            return got, poly.calls

    results, calls = asyncio.run(run()) if jobs else ([], 0)
    frames = []
    for (security_id, _, _, _), rows in zip(jobs, results):
        if rows:
            frames.append(pd.DataFrame({
                "security_id": security_id,
                "date": [datetime.fromtimestamp(r["t"] / 1000, tz=NEW_YORK).date() for r in rows],
                "open": [r.get("o") for r in rows], "high": [r.get("h") for r in rows],
                "low": [r.get("l") for r in rows], "close": [r["c"] for r in rows],
                "volume": [r.get("v") for r in rows], "vwap": [r.get("vw") for r in rows],
            }))
    rows_added = 0
    with transaction(con):
        if frames:
            frame = pd.concat(frames).drop_duplicates(["security_id", "date"])
            open_days = {d for (d,) in con.execute("SELECT date FROM calendar WHERE is_open").fetchall()}
            frame = frame[frame["date"].isin(open_days)]
            con.register("_bars", frame)
            con.execute("INSERT OR IGNORE INTO bars_daily SELECT * FROM _bars")
            con.unregister("_bars")
            rows_added = len(frame)
        for security_id in todo["security_id"].unique():
            log_fetch(con, TICKER_SOURCE, security_id, None, immutable=True)
    con.close()
    return {"securities": int(todo["security_id"].nunique()), "calls": calls, "rows": rows_added}


GAP_SOURCE = "bars_gap"
MIN_GAP = 3


def _needed_periods(con, start: date, last: date) -> pd.DataFrame:
    """(security_id, start, end) spans each security must have bars for, end exclusive."""
    return con.execute("""
        WITH spans AS (
            SELECT security_id, valid_from, valid_to FROM universe_membership WHERE security_id IS NOT NULL
            UNION ALL
            SELECT h.security_id, greatest(coalesce(m.valid_from, h.valid_from), h.valid_from),
                   CASE WHEN m.valid_to IS NULL THEN h.valid_to
                        WHEN h.valid_to IS NULL THEN m.valid_to ELSE least(m.valid_to, h.valid_to) END
            FROM universe_membership m JOIN ticker_history h ON h.ticker = m.ticker AND h.priority = 1
            WHERE m.security_id IS NULL
              AND (h.valid_to IS NULL OR m.valid_from IS NULL OR h.valid_to > m.valid_from)
              AND (m.valid_to IS NULL OR h.valid_from < m.valid_to)
        )
        SELECT security_id, greatest(coalesce(valid_from, ?), ?) AS s, least(coalesce(valid_to, ?), ?) AS e
        FROM spans
    """, [start, start, last + timedelta(days=1), last + timedelta(days=1)]).df().query("s < e")


def repair_gaps() -> dict:
    """Fetch, per ticker, any stretch of sessions a needed security is missing.

    Gaps appear when a ticker mapping is corrected after its sessions were fetched (Honeywell's
    pre-2026 HON, Fiserv's 2023–25 FI) or a security joins late. Each gap is tried once.
    """
    con = connect()
    last = con.execute("SELECT max(date) FROM calendar WHERE is_open").fetchone()[0]
    start = history_start()
    periods = _needed_periods(con, start, last)
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(
        [d for (d,) in con.execute("SELECT date FROM calendar WHERE is_open AND date >= ?", [start]).fetchall()])))
    have = con.execute("SELECT security_id, date FROM bars_daily WHERE date >= ?", [start]).df()
    have_by = {sid: set(pd.to_datetime(g["date"])) for sid, g in have.groupby("security_id")}
    tried = {k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ?", [GAP_SOURCE]).fetchall()}
    history = con.execute("SELECT security_id, ticker, valid_from, valid_to, priority FROM ticker_history "
                          "WHERE priority <= 2").df()
    jobs, keys = [], []
    for sid, group in periods.groupby("security_id"):
        need = set()
        for s, e in zip(group["s"], group["e"]):
            need |= set(sessions[(sessions >= pd.Timestamp(s)) & (sessions < pd.Timestamp(e))])
        missing = sorted(need - have_by.get(sid, set()))
        if len(missing) < MIN_GAP:
            continue
        key = f"{sid}:{missing[0].date()}"
        if key in tried:
            continue
        lo, hi = missing[0], missing[-1]
        for row in history[history["security_id"] == sid].itertuples():
            r_from = max(lo, pd.Timestamp(row.valid_from))
            r_to = min(hi, pd.Timestamp(row.valid_to) - pd.Timedelta(days=1)) if pd.notna(row.valid_to) else hi
            if r_from <= r_to:
                jobs.append((sid, row.ticker, r_from.date(), r_to.date()))
        keys.append(key)

    async def run():
        async with Polygon() as poly:
            got = await asyncio.gather(*(_ticker_range(poly, t, s, e) for _, t, s, e in jobs))
            return got, poly.calls

    results, calls = asyncio.run(run()) if jobs else ([], 0)
    frames = [pd.DataFrame({
        "security_id": sid,
        "date": [datetime.fromtimestamp(r["t"] / 1000, tz=NEW_YORK).date() for r in rows],
        "open": [r.get("o") for r in rows], "high": [r.get("h") for r in rows], "low": [r.get("l") for r in rows],
        "close": [r["c"] for r in rows], "volume": [r.get("v") for r in rows], "vwap": [r.get("vw") for r in rows],
    }) for (sid, _, _, _), rows in zip(jobs, results) if rows]
    added = 0
    with transaction(con):
        if frames:
            frame = pd.concat(frames).drop_duplicates(["security_id", "date"])
            open_days = set(sessions.date)
            frame = frame[frame["date"].isin(open_days)]
            before = con.execute("SELECT count(*) FROM bars_daily").fetchone()[0]
            con.register("_bars", frame)
            con.execute("INSERT OR IGNORE INTO bars_daily SELECT * FROM _bars")
            con.unregister("_bars")
            added = con.execute("SELECT count(*) FROM bars_daily").fetchone()[0] - before
        for key in keys:
            log_fetch(con, GAP_SOURCE, key, None, immutable=True)
    con.close()
    return {"gaps": len(keys), "calls": calls, "rows": added}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args()
    stats = backfill(args.start, args.end)
    print(f"{stats['sessions']} sessions, {stats['holidays']} holidays, {stats['unpublished']} not yet published; "
          f"{stats['rows']:,} bars from {stats['calls']} calls")


if __name__ == "__main__":
    main()
