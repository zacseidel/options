"""Short interest for tracked securities (PLAN-signals §9), from Polygon `/stocks/v1/short-interest`.

FINRA publishes short interest twice a month by settlement date, about 8 business days later. The
daily step asks for settlement dates after the latest stored one (one market-wide call per date, ~22k
rows, filtered to tracked tickers). `--backfill` fetches every tracked ticker's history instead.

Usage:  python -m market.data.short_interest [--backfill]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

import pandas as pd

from market.data.polygon import Polygon
from market.store.db import connect, log_fetch, transaction

ENDPOINT = "/stocks/v1/short-interest"
PUBLISH_LAG = 8
FIRST = "2020-06-01"
COLUMNS = ["security_id", "settlement_date", "short_interest", "avg_daily_volume", "days_to_cover", "available"]


def to_rows(con, raw: list[dict]) -> pd.DataFrame:
    """Polygon rows → table rows, mapped to securities by the ticker in use on the settlement date."""
    if not raw:
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.DataFrame(raw)
    frame["settlement_date"] = pd.to_datetime(frame["settlement_date"])
    hist = con.execute("SELECT security_id, ticker, valid_from, valid_to, priority FROM ticker_history").df()
    hist["valid_from"] = pd.to_datetime(hist["valid_from"])
    hist["valid_to"] = pd.to_datetime(hist["valid_to"]).fillna(pd.Timestamp.max)
    j = frame.reset_index().merge(hist, on="ticker")
    j = j[(j["valid_from"] <= j["settlement_date"]) & (j["valid_to"] > j["settlement_date"])]
    j = j.sort_values("priority").drop_duplicates("index")
    j = j.drop_duplicates(["security_id", "settlement_date"])
    j["available"] = j["settlement_date"] + pd.offsets.BDay(PUBLISH_LAG)
    return j[COLUMNS]


def _store(con, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    with transaction(con):
        con.register("_si", frame)
        con.execute(f"INSERT OR REPLACE INTO short_interest SELECT {', '.join(COLUMNS)} FROM _si")
        con.unregister("_si")


def backfill() -> dict:
    con = connect()
    tickers = sorted({t for (t,) in con.execute("SELECT DISTINCT ticker FROM ticker_history").fetchall()})

    async def run():
        async with Polygon() as poly:
            pages = await asyncio.gather(*(poly.paginate(ENDPOINT, {"ticker": t, "settlement_date.gte": FIRST,
                                                                    "limit": 50000}) for t in tickers),
                                         return_exceptions=True)
            return [r for p in pages if isinstance(p, list) for r in p], poly.calls

    raw, calls = asyncio.run(run())
    frame = to_rows(con, raw)
    _store(con, frame)
    log_fetch(con, "short_interest", "backfill", len(frame), immutable=False)
    con.close()
    return {"tickers": len(tickers), "rows": len(frame), "calls": calls}


def sync(today: date | None = None) -> dict:
    """New settlement dates since the latest stored one (market-wide, filtered to tracked tickers)."""
    con = connect()
    latest = con.execute("SELECT max(settlement_date) FROM short_interest").fetchone()[0]
    if latest is None:
        con.close()
        return backfill()
    start = latest + timedelta(days=1)

    async def run():
        async with Polygon() as poly:
            rows = await poly.paginate(ENDPOINT, {"settlement_date.gte": str(start), "limit": 50000})
            return rows, poly.calls

    raw, calls = asyncio.run(run())
    frame = to_rows(con, raw)
    _store(con, frame)
    log_fetch(con, "short_interest", str(today or date.today()), len(frame), immutable=False)
    con.close()
    return {"since": str(start), "rows": len(frame), "settlements": int(frame["settlement_date"].nunique()), "calls": calls}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backfill", action="store_true")
    print(backfill() if parser.parse_args().backfill else sync())


if __name__ == "__main__":
    main()
