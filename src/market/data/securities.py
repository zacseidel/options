"""Security master: stable ids (composite FIGI) and dated ticker history for the tracked set.

The tracked set is every ticker that appears in a tracked universe during the history window
(S&P 500/400 membership incl. change events), plus watchlists and benchmarks — about 1,200
strings, not the whole market. Each string is resolved to the securities that have ever used
it (active and delisted), and each security's ticker-change events give its ticker history.
That is what lets FB (2012–2022) map to Meta's id while today's FB (an ETF) stays separate.

Usage:  python -m market.data.securities
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import duckdb
import pandas as pd

from market.config import config
from market.data import watchlists
from market.data.polygon import Polygon, PolygonError
from market.store.db import connect, log_fetch, replace_rows

STOCK_TYPES = {"CS", "ADRC"}
BENCHMARK_TYPES = {"ETF"}


def history_start(today: date | None = None) -> date:
    """First session inside the plan's rolling 5-year window (with a week of margin)."""
    today = today or date.today()
    years = config()["polygon"]["stocks_history_years"]
    try:
        anchor = today.replace(year=today.year - years)
    except ValueError:                      # Feb 29
        anchor = today.replace(year=today.year - years, day=28)
    return anchor + timedelta(days=7)


def candidate_tickers(con: duckdb.DuckDBPyConnection, start: date) -> set[str]:
    universes = config()["tracked"]["universes"]
    marks = ",".join("?" * len(universes))
    members = con.execute(
        f"""SELECT DISTINCT ticker FROM universe_membership
            WHERE universe IN ({marks}) AND (valid_to IS NULL OR valid_to > ?)""",
        [*universes, start],
    ).df()["ticker"]
    changed = con.execute(
        f"SELECT DISTINCT ticker FROM universe_changes WHERE universe IN ({marks}) AND date >= ?",
        [*universes, start],
    ).df()["ticker"]
    tickers = set(members) | set(changed)
    if config()["tracked"].get("watchlists"):
        tickers |= {t for wl in watchlists.load() for t in wl.tickers}
    return {t for t in tickers if t and t[0].isalpha()}


def _date(value) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


async def _lookup(poly: Polygon, ticker: str) -> list[dict]:
    """Every security (active or delisted) that currently lists or last listed `ticker`."""
    rows = []
    for active in ("true", "false"):
        try:
            body = await poly.get(
                "/v3/reference/tickers", {"ticker": ticker, "market": "stocks", "active": active, "limit": 100}
            )
        except PolygonError:
            continue
        rows.extend(body.get("results") or [])
    return rows


async def _events(poly: Polygon, figi: str) -> list[dict]:
    try:
        body = await poly.get(f"/vX/reference/tickers/{figi}/events", {"types": "ticker_change"})
    except PolygonError:
        return []
    return (body.get("results") or {}).get("events") or []


EARLIEST = date(1900, 1, 1)


def ticker_history_rows(
    security_id: str, current_ticker: str, delisted: date | None, events: list[dict], observed: set[str] = frozenset()
) -> list[dict]:
    """Ticker-change events → [ticker, valid_from, valid_to) rows (valid_to exclusive).

    Polygon's events are incomplete (GOOGL's list only 'GOOG', BRK.B's only 'BRK'), so the
    final segment always carries the ticker the reference lookup returned — authoritative for
    today, or for the delisting date. Other tickers seen for this security become priority-2
    aliases over its whole life.
    """
    changes = sorted(
        ((_date(e["date"]), e["ticker_change"]["ticker"]) for e in events
         if e.get("type") == "ticker_change" and e.get("date") and e.get("ticker_change")),
        key=lambda item: item[0],
    )
    rows = []
    for i, (start, ticker) in enumerate(changes):
        end = changes[i + 1][0] if i + 1 < len(changes) else delisted
        rows.append({"security_id": security_id, "ticker": ticker,
                     "valid_from": EARLIEST if i == 0 else start, "valid_to": end, "priority": 1})
    if rows:
        rows[-1]["ticker"] = current_ticker
    else:
        rows.append({"security_id": security_id, "ticker": current_ticker,
                     "valid_from": EARLIEST, "valid_to": delisted, "priority": 1})
    covered = {r["ticker"] for r in rows}
    for alias in sorted(set(observed) - covered):
        rows.append({"security_id": security_id, "ticker": alias,
                     "valid_from": EARLIEST, "valid_to": delisted, "priority": 2})
    return rows


async def resolve(tickers: set[str], benchmarks: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    async with Polygon() as poly:
        names = sorted(tickers | benchmarks)
        found = await asyncio.gather(*(_lookup(poly, t) for t in names))
        records: dict[str, dict] = {}
        observed: dict[str, set[str]] = {}
        for ticker, rows in zip(names, found):
            allowed = STOCK_TYPES | (BENCHMARK_TYPES if ticker in benchmarks else set())
            for row in rows:
                if row.get("type") not in allowed:
                    continue
                figi = row.get("composite_figi")
                delisted = _date(row.get("delisted_utc"))
                security_id = figi or f"T:{row['ticker']}:{delisted or 'active'}"
                observed.setdefault(security_id, set()).add(row["ticker"])
                existing = records.get(security_id)
                # Prefer the active record; among delisted ones, the latest delisting.
                newer = existing is None or (row.get("active") and existing["delist_date"] is not None) or (
                    not row.get("active") and existing["delist_date"] is not None
                    and delisted and delisted > existing["delist_date"]
                )
                if newer:
                    records[security_id] = {
                        "security_id": security_id, "figi": figi, "ticker": row["ticker"], "name": row.get("name"),
                        "type": row.get("type"), "exchange": row.get("primary_exchange"),
                        "list_date": None, "delist_date": None if row.get("active") else delisted,
                        "cik": row.get("cik"),
                    }
        figis = [r["security_id"] for r in records.values() if r["figi"]]
        events = dict(zip(figis, await asyncio.gather(*(_events(poly, f) for f in figis))))
        calls = poly.calls

    history = []
    for record in records.values():
        sid = record["security_id"]
        history.extend(ticker_history_rows(
            sid, record["ticker"], record["delist_date"], events.get(sid, []), observed.get(sid, set())
        ))
    return pd.DataFrame(list(records.values())), pd.DataFrame(history), calls


def synthetic_rows(needs: dict[str, date | None]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stand-ins for index members Polygon has no matching stock record for.

    needs: ticker → last index day (None = still a member). The stand-in's ticker is valid
    only until 30 days after that, so a later reuse of the ticker (INFO is an ETF today,
    COR is Cencora) can never be mapped onto it — and priority 3 loses to any real record.
    """
    securities, history = [], []
    for ticker, last_day in sorted(needs.items()):
        valid_to = None if last_day is None else last_day + timedelta(days=30)
        sid = f"T:{ticker}:{valid_to or 'active'}"
        securities.append({"security_id": sid, "figi": None, "ticker": ticker, "name": None, "type": "CS",
                           "exchange": None, "list_date": None, "delist_date": valid_to, "cik": None})
        history.append({"security_id": sid, "ticker": ticker, "valid_from": EARLIEST, "valid_to": valid_to, "priority": 3})
    return pd.DataFrame(securities), pd.DataFrame(history)


def unmatched_members(con: duckdb.DuckDBPyConnection, history: pd.DataFrame, start: date) -> dict[str, date | None]:
    """In-window membership periods that no security's use of the ticker overlaps.

    A delisting may precede the index removal by days (ATVI, HES), so a record ending up to
    30 days before the period starts still counts. A record that only begins after the period
    ends does not (Healthpeak took 'DOC' after Physicians Realty left the S&P 400).
    """
    universes = config()["tracked"]["universes"]
    periods = con.execute(
        f"""SELECT ticker, valid_from, valid_to FROM universe_membership
            WHERE universe IN ({','.join('?' * len(universes))}) AND (valid_to IS NULL OR valid_to > ?)""",
        [*universes, start],
    ).df()
    rows_from = pd.to_datetime(history["valid_from"])
    rows_to = (pd.to_datetime(history["valid_to"]) + pd.Timedelta(days=30)).fillna(pd.Timestamp.max)
    needs: dict[str, date | None] = {}
    for ticker, valid_from, valid_to in zip(periods["ticker"], periods["valid_from"], periods["valid_to"]):
        p_from = pd.Timestamp(valid_from) if pd.notna(valid_from) else pd.Timestamp.min
        p_to = pd.Timestamp(valid_to) if pd.notna(valid_to) else pd.Timestamp.max
        same = history["ticker"] == ticker
        if not (same & (rows_from < p_to) & (rows_to > p_from)).any():
            needs[ticker] = None if pd.isna(valid_to) else pd.Timestamp(valid_to).date() - timedelta(days=1)
    return needs


def ticker_map(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT h.security_id, h.ticker, h.valid_from, h.valid_to, h.priority, s.type
        FROM ticker_history h JOIN securities s USING (security_id)
    """).df()


def tickers_on(history: pd.DataFrame, on: date) -> dict[str, str]:
    """ticker → security_id for every ticker valid on `on` (best priority, then common stock)."""
    on_ts = pd.Timestamp(on)
    valid = history[(pd.to_datetime(history["valid_from"]) <= on_ts)
                    & (pd.to_datetime(history["valid_to"]).fillna(pd.Timestamp.max) > on_ts)]
    valid = valid.assign(_stock=~valid["type"].isin(STOCK_TYPES)).sort_values(["priority", "_stock"])
    return dict(valid.drop_duplicates("ticker")[["ticker", "security_id"]].itertuples(index=False, name=None))


def security_for(history: pd.DataFrame, ticker: str, on: date, slack_days: int = 120) -> str | None:
    """Security using `ticker` on `on`; tolerates renames recorded late by the source."""
    rows = history[history["ticker"] == ticker]
    if rows.empty:
        return None
    exact = tickers_on(rows, on).get(ticker)
    if exact:
        return exact
    for shift in (slack_days, -slack_days):
        hit = tickers_on(rows, on + timedelta(days=shift)).get(ticker)
        if hit:
            return hit
    return None


def sync() -> dict:
    con = connect()
    start = history_start()
    tickers = candidate_tickers(con, start)
    benchmarks = set(config()["tracked"]["benchmarks"])
    securities, history, calls = asyncio.run(resolve(tickers, benchmarks))
    aliases = config()["tracked"].get("ticker_aliases") or {}
    alias_rows = [
        {"security_id": sid, "ticker": old, "valid_from": EARLIEST, "valid_to": None, "priority": 2}
        for old, new in aliases.items()
        for sid in securities.loc[securities["ticker"] == new, "security_id"]
    ]
    history = pd.concat([history, pd.DataFrame(alias_rows)], ignore_index=True)
    typed = history.merge(securities[["security_id", "type"]], on="security_id", how="left")
    needs = unmatched_members(con, typed, start)
    unresolved = set(needs)
    extra_securities, extra_history = synthetic_rows(needs)
    securities = pd.concat([securities, extra_securities], ignore_index=True)
    history = pd.concat([history, extra_history], ignore_index=True)
    replace_rows(con, "securities", securities, "TRUE", [])
    replace_rows(con, "ticker_history", history, "TRUE", [])
    log_fetch(con, "securities", str(date.today()), len(securities), immutable=False)
    con.close()
    return {"candidates": len(tickers), "securities": len(securities), "ticker_rows": len(history),
            "calls": calls, "synthetic": sorted(unresolved)}


def main() -> None:
    report = sync()
    print(f"{report['candidates']} candidate tickers → {report['securities']} securities, "
          f"{report['ticker_rows']} ticker-history rows ({report['calls']} API calls)")
    print(f"synthetic stand-ins ({len(report['synthetic'])}): {report['synthetic']}")


if __name__ == "__main__":
    main()
