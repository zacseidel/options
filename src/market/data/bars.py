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
from market.data.securities import history_start, ticker_map, tickers_on
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


def _to_frame(rows: list[dict], session: date, mapping: dict[str, str]) -> pd.DataFrame:
    kept = [r for r in rows if r.get("T") in mapping and r.get("c") is not None]
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
                            frame = _to_frame(rows, session, tickers_on(history, session))
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
