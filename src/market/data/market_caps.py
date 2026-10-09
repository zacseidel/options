"""Point-in-time company market caps for S&P 500 members (for megacap / top-N-by-size cohorts).

One ticker-details call per member per quarter end (`date=` makes it point-in-time; the
value is company-level, so GOOG and GOOGL report the same number). Between anchors the cap
is carried forward with the split-adjusted price ratio, so daily ranking needs no more calls.
This stands in for SSGA index weights, which have no history (float adjustment aside, the
ranking is the same).

Usage:  python -m market.data.market_caps
"""

from __future__ import annotations

import asyncio
from datetime import date

import duckdb
import pandas as pd

from market.data.polygon import Polygon, PolygonError
from market.data.securities import history_start
from market.store.db import already_fetched, connect, log_fetch, transaction
from market.store.panel import Panel

UNIVERSE = "sp500"
SOURCE = "market_caps"


def anchor_dates(start: date, end: date) -> list[date]:
    quarter_ends = [d.date() for d in pd.date_range(start, end, freq="QE")]
    return quarter_ends + ([end] if not quarter_ends or quarter_ends[-1] < end else [])


def members_with_tickers(con: duckdb.DuckDBPyConnection, on: date) -> list[tuple[str, str]]:
    """(security_id, ticker as of `on`) for S&P 500 members on that date."""
    return con.execute("""
        SELECT m.security_id, h.ticker
        FROM universe_membership m
        JOIN ticker_history h ON h.security_id = m.security_id
             AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)
        WHERE m.universe = ? AND m.source = 'wikipedia' AND m.security_id IS NOT NULL
          AND (m.valid_from IS NULL OR m.valid_from <= ?) AND (m.valid_to IS NULL OR m.valid_to > ?)
        QUALIFY row_number() OVER (PARTITION BY m.security_id ORDER BY h.priority) = 1
    """, [on, on, UNIVERSE, on, on]).fetchall()


async def _details(poly: Polygon, ticker: str, on: date) -> dict | None:
    try:
        body = await poly.get(f"/v3/reference/tickers/{ticker}", {"date": str(on)})
    except PolygonError:
        return None
    return body.get("results")


def sync(end: date | None = None) -> dict:
    con = connect()
    end = end or date.today()
    anchors = [d for d in anchor_dates(history_start(), end) if not already_fetched(con, SOURCE, str(d))]
    stats = {"anchors": len(anchors), "rows": 0, "missing": 0, "calls": 0}

    async def run() -> None:
        async with Polygon() as poly:
            for anchor in anchors:
                members = members_with_tickers(con, anchor)
                details = await asyncio.gather(*(_details(poly, t, anchor) for _, t in members))
                rows = [
                    (sid, anchor, d.get("market_cap"), d.get("weighted_shares_outstanding"))
                    for (sid, _), d in zip(members, details) if d and d.get("market_cap")
                ]
                stats["missing"] += len(members) - len(rows)
                with transaction(con):
                    con.execute("DELETE FROM market_caps WHERE date = ?", [anchor])
                    con.executemany("INSERT INTO market_caps VALUES (?, ?, ?, ?)", rows)
                    # Quarter ends are immutable; the latest (today) anchor is refreshed next run.
                    log_fetch(con, SOURCE, str(anchor), len(rows), immutable=anchor < end)
                stats["rows"] += len(rows)
                print(f"   {anchor}: {len(rows)}/{len(members)} members", flush=True)
            stats["calls"] = poly.calls

    try:
        asyncio.run(run())
    finally:
        con.close()
    return stats


def daily_market_caps(con: duckdb.DuckDBPyConnection, panel: Panel) -> pd.DataFrame:
    """sessions × security_id market caps: last anchor carried forward by adjusted price ratio."""
    anchors = con.execute("SELECT security_id, date, market_cap FROM market_caps").df()
    anchors["date"] = pd.to_datetime(anchors["date"])
    cap = anchors.pivot(index="date", columns="security_id", values="market_cap")
    cap = cap.reindex(columns=panel.close.columns)
    # Anchor dates may be non-sessions (quarter ends on weekends): price them at the prior session.
    anchor_sessions = [panel.session_on_or_before(d) for d in cap.index]
    anchor_close = panel.close.reindex(anchor_sessions).set_axis(cap.index)
    cap_per_price = (cap / anchor_close).reindex(panel.sessions.union(cap.index)).ffill().reindex(panel.sessions)
    return cap_per_price * panel.close


def main() -> None:
    stats = sync()
    print(f"{stats['rows']:,} market caps over {stats['anchors']} anchors "
          f"({stats['missing']} member-quarters missing, {stats['calls']} calls)")


if __name__ == "__main__":
    main()
