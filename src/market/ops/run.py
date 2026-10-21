"""Daily update: every step idempotent and incremental (PLAN §11).

  1. watchlists        sync watchlists.yaml into universe membership
  2. universes         Wikipedia + security master + id replay — weekly, or with --full
  3. disclosures       new Congress PTRs (House, Senate) and 13F filings (EDGAR daily index)
  4. bars              grouped daily for any session not yet stored
  5. fund_periods      price 13F holding periods completed since the last run
  6. signals           Congress / 13F names → security master, bars, splits; repair bar gaps
  7. corporate actions last 60 days daily; whole window weekly
  8. market caps       any quarter-end anchor not yet stored (+ refresh the latest weekly)
  9. leaders           point-in-time Congress member and 13F fund leaderboards per report date
 10. fundamentals      EDGAR companyfacts for new companies and the day's 10-K / 10-Q filers
 11. option_flow       one-row-per-underlying summary of each new OPRA file (option-flow categories)
 12. categories        recompute recent report dates; full rebuild when a category's code changed
 13. options           option bars for the select option set (previous session's OPRA file, plus a
                       batched re-stream for names newly entering an option slot)
 14. evaluation        all strategies, stock and option (derived)
 15. export            site/data JSON
 16. publish           (not configured yet)

Usage:  python -m market.ops.run [--full] [--only STEP ...] [--skip STEP ...]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from datetime import date, datetime, timedelta

import pandas as pd

import market.categories.catalog  # noqa: F401  (registers categories)
from market.categories.registry import REGISTRY
from market.config import ROOT
from market.data import (bars, corpactions, fundamentals, market_caps, option_panel, securities, universe_wiki,
                         watchlists)
from market.evaluate import engine
from market.reports import export, snapshot
from market.smartmoney import hedge, ingest, pipeline
from market.store.db import connect

STEPS = ["watchlists", "universes", "disclosures", "bars", "fund_periods", "signals", "corpactions", "market_caps",
         "leaders", "fundamentals", "option_flow", "categories", "options", "evaluation", "export"]
WEEKLY_DAY = 0                      # Monday: refresh slower-moving reference data


def _last_fetch(con, source: str) -> date | None:
    row = con.execute("SELECT max(fetched_at) FROM fetch_log WHERE source = ?", [source]).fetchone()
    return row[0].date() if row and row[0] else None


def _weekly_due(con, source: str, full: bool) -> bool:
    last = _last_fetch(con, source)
    return full or last is None or (date.today() - last).days >= 7 or date.today().weekday() == WEEKLY_DAY and last < date.today()


def step_watchlists(full: bool) -> dict:
    con = connect()
    report = watchlists.sync(con, watchlists.load())
    con.close()
    return {name: {k: v for k, v in info.items() if v} for name, info in report.items()}


def step_universes(full: bool) -> dict:
    con = connect()
    due = _weekly_due(con, "wiki_sp500", full)
    con.close()
    if not due:
        return {"skipped": "refreshed within the week"}
    wiki = universe_wiki.sync(list(universe_wiki.PAGES))
    secs = securities.sync()
    con = connect()
    resolved = universe_wiki.resolve_membership(con)
    con.close()
    return {"members": {u: (i["coverage_min"], i["coverage_max"]) for u, i in resolved.items()},
            "change_events": {u: i["change_events"] for u, i in wiki.items()},
            "securities": secs["securities"], "synthetic": secs["synthetic"]}


def step_disclosures(full: bool) -> dict:
    return ingest.run()


def step_fund_periods(full: bool) -> dict:
    return hedge.sync_periods()


def step_signals(full: bool) -> dict:
    return pipeline.signals(full)


def step_leaders(full: bool) -> dict:
    return pipeline.leaders(full)


def step_bars(full: bool) -> dict:
    stats = bars.backfill()
    return {k: stats[k] for k in ("sessions", "holidays", "unpublished", "rows")}


def step_corpactions(full: bool) -> dict:
    con = connect()
    weekly = _weekly_due(con, "corpactions_full", full)
    con.close()
    start = None if weekly else date.today() - timedelta(days=60)
    stats = corpactions.sync(start)
    if weekly:
        con = connect()
        con.execute("INSERT OR REPLACE INTO fetch_log VALUES ('corpactions_full', ?, ?, ?, FALSE)",
                    [str(date.today()), datetime.now(), stats["splits_kept"] + stats["dividends_kept"]])
        con.close()
    return {"scope": "full window" if weekly else "last 60 days", **stats}


def step_market_caps(full: bool) -> dict:
    con = connect()
    latest_due = _weekly_due(con, "market_caps_latest", full)
    if not latest_due:
        # Drop today's provisional anchor from the pending set by marking it fetched for the week.
        con.execute("INSERT OR REPLACE INTO fetch_log VALUES ('market_caps', ?, ?, 0, TRUE)", [str(date.today()), datetime.now()])
    con.close()
    stats = market_caps.sync()
    if latest_due:
        con = connect()
        con.execute("INSERT OR REPLACE INTO fetch_log VALUES ('market_caps_latest', ?, ?, ?, FALSE)",
                    [str(date.today()), datetime.now(), stats["rows"]])
        con.close()
    return stats


def step_categories(full: bool) -> dict:
    con = connect()
    stored = dict(con.execute(
        "SELECT category_id, any_value(version) FROM category_snapshots WHERE origin = 'backtest' GROUP BY 1"
    ).fetchall())
    last = con.execute("SELECT max(report_date) FROM category_snapshots WHERE origin = 'backtest'").fetchone()[0]
    con.close()
    stale = [c for c, cat in REGISTRY.items() if full or stored.get(c) != cat.version]
    fresh = [c for c in REGISTRY if c not in stale]
    out = {}
    if stale:
        out["rebuilt"] = snapshot.build(None, None, stale)
    if fresh and last:
        start = pd.Timestamp(last).date() - timedelta(days=7)
        out["updated"] = snapshot.build(start, None, fresh)
    return {"rebuilt": stale, "updated": fresh, "seconds": sum(v.get("_seconds", 0) for v in out.values())}


def step_fundamentals(full: bool) -> dict:
    """EDGAR companyfacts for companies never fetched and for the day's 10-K / 10-Q filers."""
    return fundamentals.sync()


def step_option_flow(full: bool) -> dict:
    """Option-flow summaries first, so the option-flow categories see the latest session."""
    return option_panel.sync(flow_only=True)


def step_options(full: bool) -> dict:
    return option_panel.sync()


def step_evaluation(full: bool) -> dict:
    return engine.evaluate()


def step_export(full: bool) -> dict:
    return export.export()


RUNNERS = {name: globals()[f"step_{name}"] for name in STEPS}


def code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def run(steps: list[str], full: bool) -> bool:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    started = datetime.now()
    con = connect()
    con.execute("INSERT INTO runs (run_id, started_at, status, code_version) VALUES (?, ?, 'running', ?)",
                [run_id, started, code_version()])
    con.close()
    summary, ok = {}, True
    for name in steps:
        t0 = time.time()
        print(f"▶ {name}", flush=True)
        try:
            result = RUNNERS[name](full)
            summary[name] = {"ok": True, "seconds": round(time.time() - t0, 1), "result": result}
            print(f"  ✓ {name} ({summary[name]['seconds']}s): {json.dumps(result, default=str)[:300]}", flush=True)
        except Exception as exc:                     # keep going: later steps may still be useful
            ok = False
            summary[name] = {"ok": False, "seconds": round(time.time() - t0, 1), "error": repr(exc)}
            print(f"  ✗ {name}: {exc!r}\n{traceback.format_exc()}", flush=True)
    con = connect()
    through = con.execute("SELECT max(date) FROM calendar WHERE is_open").fetchone()[0]
    con.execute("UPDATE runs SET finished_at = ?, status = ?, data_through = ?, summary = ? WHERE run_id = ?",
                [datetime.now(), "ok" if ok else "failed", through, json.dumps(summary, default=str), run_id])
    con.close()
    print(f"{'✅' if ok else '❌'} run {run_id} finished in {(datetime.now() - started).seconds}s; data through {through}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily update")
    parser.add_argument("--full", action="store_true", help="refresh weekly reference data and rebuild all categories")
    parser.add_argument("--only", nargs="+", choices=STEPS)
    parser.add_argument("--skip", nargs="+", choices=STEPS, default=[])
    args = parser.parse_args()
    steps = [s for s in (args.only or STEPS) if s not in args.skip]
    raise SystemExit(0 if run(steps, args.full) else 1)


if __name__ == "__main__":
    main()
