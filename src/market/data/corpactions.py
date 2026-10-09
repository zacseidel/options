"""Splits and cash dividends for the tracked set.

Queried per tracked ticker string (every ticker in ticker_history, so pre-rename names are
covered) in parallel — filtering at the source instead of paging the whole market. Each row
is mapped to a tracked security by ticker as of its ex-date. Re-running replaces the window (corporate-action feeds get
late corrections, so this is not marked immutable).

Usage:  python -m market.data.corpactions [--start YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

import pandas as pd

from market.data.polygon import Polygon
from market.data.securities import history_start, ticker_map, tickers_on
from market.store.db import connect, log_fetch, replace_rows


def _map(rows: list[dict], date_key: str, history: pd.DataFrame) -> list[tuple[dict, str]]:
    by_day: dict[str, dict[str, str]] = {}
    out = []
    for row in rows:
        day = row.get(date_key)
        if not day:
            continue
        if day not in by_day:
            by_day[day] = tickers_on(history, date.fromisoformat(day))
        sid = by_day[day].get(row.get("ticker"))
        if sid:
            out.append((row, sid))
    return out


RECENT_DAYS = 120   # windows this short use the market-wide feed (a few pages) instead of per-ticker calls


async def _fetch_market_wide(start: date) -> tuple[list[dict], list[dict], int]:
    horizon = date.today() + timedelta(days=90)
    async with Polygon() as poly:
        splits, dividends = await asyncio.gather(
            poly.paginate("/v3/reference/splits", {"execution_date.gte": str(start), "execution_date.lte": str(horizon),
                                                  "sort": "execution_date", "order": "asc", "limit": 1000}),
            poly.paginate("/v3/reference/dividends", {"ex_dividend_date.gte": str(start), "ex_dividend_date.lte": str(horizon),
                                                     "sort": "ex_dividend_date", "order": "asc", "limit": 1000}),
        )
        return splits, dividends, poly.calls


async def _fetch(start: date, tickers: list[str]) -> tuple[list[dict], list[dict], int]:
    horizon = date.today() + timedelta(days=90)     # announced actions only; far-future rows are noise
    async with Polygon() as poly:
        async def one(endpoint: str, key: str, ticker: str) -> list[dict]:
            return await poly.paginate(endpoint, {
                "ticker": ticker, f"{key}.gte": str(start), f"{key}.lte": str(horizon), "limit": 1000,
            })
        splits = await asyncio.gather(*(one("/v3/reference/splits", "execution_date", t) for t in tickers))
        dividends = await asyncio.gather(*(one("/v3/reference/dividends", "ex_dividend_date", t) for t in tickers))
        return [r for rows in splits for r in rows], [r for rows in dividends for r in rows], poly.calls


def sync(start: date | None = None) -> dict:
    start = start or history_start()
    con = connect()
    history = ticker_map(con)
    if (date.today() - start).days <= RECENT_DAYS:
        splits, dividends, calls = asyncio.run(_fetch_market_wide(start))
    else:
        splits, dividends, calls = asyncio.run(_fetch(start, sorted(set(history["ticker"]))))

    split_rows = pd.DataFrame([
        {"security_id": sid, "ex_date": r["execution_date"], "split_from": r["split_from"], "split_to": r["split_to"]}
        for r, sid in _map(splits, "execution_date", history)
        if r.get("split_from") and r.get("split_to")
    ], columns=["security_id", "ex_date", "split_from", "split_to"]).drop_duplicates(["security_id", "ex_date"])
    dividend_rows = pd.DataFrame([
        {"security_id": sid, "ex_date": r["ex_dividend_date"], "pay_date": r.get("pay_date"),
         "amount": r["cash_amount"], "kind": r.get("dividend_type") or "CD"}
        for r, sid in _map(dividends, "ex_dividend_date", history)
        if r.get("cash_amount")
    ], columns=["security_id", "ex_date", "pay_date", "amount", "kind"]).drop_duplicates(["security_id", "ex_date", "kind"])

    replace_rows(con, "splits", split_rows, "ex_date >= ?", [start])
    replace_rows(con, "dividends", dividend_rows, "ex_date >= ?", [start])
    log_fetch(con, "corpactions", str(date.today()), len(split_rows) + len(dividend_rows), immutable=False)
    con.close()
    return {"splits_seen": len(splits), "splits_kept": len(split_rows),
            "dividends_seen": len(dividends), "dividends_kept": len(dividend_rows), "calls": calls}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat)
    args = parser.parse_args()
    stats = sync(args.start)
    print(f"splits {stats['splits_kept']}/{stats['splits_seen']}, dividends {stats['dividends_kept']}/"
          f"{stats['dividends_seen']} kept for the tracked set ({stats['calls']} calls)")


if __name__ == "__main__":
    main()
