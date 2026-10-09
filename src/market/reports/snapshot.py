"""Compute category snapshots for report dates (backtest history or today's live report).

Usage:  python -m market.reports.snapshot [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--category ID ...]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date

import duckdb
import pandas as pd

import market.categories.catalog  # noqa: F401  (registers categories)
from market.categories.registry import REGISTRY, Category, Context
from market.data.market_caps import daily_market_caps
from market.smartmoney.signals import SmartMoney
from market.store.db import connect, replace_rows
from market.store.panel import Panel, load_panel

REPORT_WEEKDAYS = (1, 4)          # Tuesday, Friday — the momentum report cadence


def report_dates(start: date, end: date) -> list[date]:
    return [d.date() for d in pd.date_range(start, end) if d.weekday() in REPORT_WEEKDAYS]


def shared_inputs(con: duckdb.DuckDBPyConnection, panel: Panel) -> dict:
    membership = con.execute(
        "SELECT universe, security_id, valid_from, valid_to FROM universe_membership WHERE security_id IS NOT NULL"
    ).df()
    securities = con.execute("SELECT security_id, ticker, cik, name FROM securities").df().set_index("security_id")
    dollar_volume = (panel.raw_close * panel.volume).rolling(60, min_periods=20).mean()
    return {"membership": membership, "caps": daily_market_caps(con, panel),
            "securities": securities, "dollar_volume": dollar_volume, "signals": SmartMoney(con, panel)}


def ticker_lookup(con: duckdb.DuckDBPyConnection):
    history = con.execute("SELECT security_id, ticker, valid_from, valid_to, priority FROM ticker_history").df()
    history["valid_from"] = pd.to_datetime(history["valid_from"])
    history["valid_to"] = pd.to_datetime(history["valid_to"]).fillna(pd.Timestamp.max)
    history = history.sort_values("priority")

    def ticker_on(security_id: str, when: date) -> str | None:
        rows = history[(history["security_id"] == security_id) & (history["valid_from"] <= pd.Timestamp(when))
                       & (history["valid_to"] > pd.Timestamp(when))]
        return rows["ticker"].iloc[0] if len(rows) else None
    return ticker_on


def first_computable(panel: Panel, cat: Category) -> date:
    return panel.sessions[min(cat.lookback_sessions, len(panel.sessions) - 1)].date()


def rows_for(cat: Category, ctx: Context, frame: pd.DataFrame, ticker_on, origin: str) -> list[dict]:
    rows = []
    for rank, (security_id, record) in enumerate(frame.iterrows(), start=1):
        features = {k: (None if pd.isna(v) else (float(v) if isinstance(v, (int, float)) else str(v)))
                    for k, v in record.drop(labels=["score"], errors="ignore").items()}
        rows.append({
            "category_id": cat.id, "report_date": ctx.report_date, "as_of": ctx.as_of.date(),
            "security_id": security_id, "ticker": ticker_on(security_id, ctx.as_of.date()), "rank": rank,
            "score": None if pd.isna(record.get("score")) else float(record["score"]),
            "features": json.dumps(features), "origin": origin, "version": cat.version,
        })
    return rows


def build(start: date | None, end: date | None, categories: list[str] | None, origin: str = "backtest") -> dict:
    con = connect()
    t0 = time.time()
    panel = load_panel(con)
    inputs = shared_inputs(con, panel)
    ticker_on = ticker_lookup(con)
    end = end or date.today()
    stats = {}
    for cat_id in categories or list(REGISTRY):
        cat = REGISTRY[cat_id]
        first = max(start or date.min, first_computable(panel, cat))
        dates = [d for d in report_dates(first, end) if panel.session_on_or_before(d) is not None]
        rows = []
        for report_date in dates:
            ctx = Context(report_date=report_date, panel=panel, **inputs)
            if ctx.as_of is None or ctx.as_of.date() >= report_date:
                continue
            rows.extend(rows_for(cat, ctx, cat.compute(ctx), ticker_on, origin))
        frame = pd.DataFrame(rows)
        replace_rows(con, "category_snapshots", frame,
                     "category_id = ? AND origin = ? AND report_date BETWEEN ? AND ?",
                     [cat.id, origin, dates[0], dates[-1]])
        stats[cat.id] = {"reports": len(dates), "rows": len(frame), "first": str(dates[0]), "last": str(dates[-1])}
    con.close()
    stats["_seconds"] = round(time.time() - t0, 1)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--category", nargs="+", choices=list(REGISTRY))
    args = parser.parse_args()
    for key, value in build(args.start, args.end, args.category).items():
        print(f"{key:18} {value}")


if __name__ == "__main__":
    main()
