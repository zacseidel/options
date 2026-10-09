"""Export the static site's JSON (site/data/), regenerated each run and never versioned.

Layout (small files, loaded per page):
  meta.json                 categories, strategies (+ metrics per window), benchmarks, report dates
  sessions.json             the trading-session calendar shared by every series
  categories/<id>.json      full report history for one category (any report / diff is derived in the browser)
  strategies/<id>.json      NAV (total + price) with aligned benchmarks, trades
  stocks/<TICKER>.json      closes, category history, strategy trades, Congress and 13F context
  congress.json             Congress members, trades and leaderboards per report date
  hedge.json                13F funds, filings (new buys / exits) and leaderboards per report date

Usage:  python -m market.reports.export
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime

import duckdb
import pandas as pd

import market.categories.catalog  # noqa: F401  (registers categories)
from market.categories.registry import REGISTRY
from market.config import config, directory
from market.reports import export_smartmoney
from market.data import watchlists
from market.evaluate.engine import load_strategies
from market.store.db import connect
from market.store.panel import load_panel

KEY_FEATURES = {
    "mom12_sp500": ["return_12m", "return_1w", "rank_change"],
    "mom12_sp400": ["return_12m", "return_1w", "rank_change"],
    "mom12_megacap": ["return_12m", "return_1w", "rank_change"],
    "laggards_mega10": ["return_3m", "return_6m", "return_12m", "avg_rank"],
    "munger_top50": ["pct_vs_sma200", "dip_date", "market_cap"],
    "rankmom_sp500": ["avg_rank", "return_3m", "return_6m", "return_12m"],
    "rankmom_sp400": ["avg_rank", "return_3m", "return_6m", "return_12m"],
    "rankfast_sp500": ["avg_rank", "return_1m", "return_3m", "return_6m"],
    "rankfast_sp400": ["avg_rank", "return_1m", "return_3m", "return_6m"],
    "congress_buys": ["members", "dollars", "last_disclosed"],
    "congress_holdings": ["members", "dollars", "return_since"],
    "hedge_buys": ["funds", "top_funds", "value"],
    "hedge_drivers": ["funds", "held_by"],
}
HOLD_LABELS = {
    "while_listed": "hold while listed",
    "fixed_hold": "hold {sessions} sessions per listing",
    "price_exit": "exit when close {exit_when} {indicator}{window}",
}


def _num(value, digits=6):
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    return round(float(value), digits)


def _clean(value):
    """JSON-safe: NaN/inf/NaT → null (browsers reject NaN), recursively."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value is pd.NaT or (not isinstance(value, (str, bytes, list, dict)) and pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return value


def _write(target, payload) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(payload), separators=(",", ":"), default=str, allow_nan=False)
    target.write_text(text)
    return len(text)


def strategy_label(strategy) -> dict:
    cat = REGISTRY[strategy.category]
    slot = "all signals" if strategy.slot == "all" else (
        f"top {strategy.slot[1]}" if strategy.slot[0] == 1 else f"ranks {strategy.slot[0]}–{strategy.slot[1]}")
    hold = HOLD_LABELS[strategy.hold].format(**{k: str(v).upper() if k == "indicator" else v
                                                for k, v in strategy.params.items()})
    return {"name": f"{cat.name} · {slot}", "slot": slot, "hold": hold, "instrument": strategy.instrument}


def current_tickers(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(con.execute("SELECT security_id, ticker FROM securities").fetchall())


def export() -> dict:
    out_dir = directory("site_out")
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    con = connect()
    sizes: dict[str, int] = {}
    key_of = current_tickers(con)
    sessions = [d.date().isoformat() for d in pd.to_datetime(
        con.execute("SELECT date FROM calendar WHERE is_open ORDER BY date").df()["date"])]
    sizes["sessions"] = _write(out_dir / "sessions.json", sessions)
    session_index = {d: i for i, d in enumerate(sessions)}

    # ---------------------------------------------------------------- categories
    snaps = con.execute("""
        SELECT category_id, report_date, as_of, security_id, ticker, rank, score, features
        FROM category_snapshots WHERE origin = 'backtest' ORDER BY category_id, report_date, rank
    """).df()
    snaps["report_date"] = pd.to_datetime(snaps["report_date"]).dt.date.astype(str)
    category_meta = []
    order = {cat_id: i for i, cat_id in enumerate(REGISTRY)}
    for cat_id, frame in sorted(snaps.groupby("category_id"), key=lambda item: order.get(item[0], 99)):
        cat = REGISTRY[cat_id]
        dates = sorted(frame["report_date"].unique())
        index = {d: i for i, d in enumerate(dates)}
        keys = KEY_FEATURES.get(cat_id, [])
        rows = []
        for r in frame.itertuples(index=False):
            feats = json.loads(r.features)
            rows.append([index[r.report_date], r.ticker, key_of.get(r.security_id, r.ticker), int(r.rank),
                         _num(r.score)] + [feats.get(k) if isinstance(feats.get(k), str) else _num(feats.get(k)) for k in keys])
        sizes[f"categories/{cat_id}"] = _write(out_dir / "categories" / f"{cat_id}.json", {
            "id": cat_id, "dates": dates, "fields": ["d", "ticker", "key", "rank", "score", *keys], "rows": rows,
        })
        latest = frame[frame["report_date"] == dates[-1]]
        category_meta.append({
            "id": cat_id, "name": cat.name, "group": cat.group, "universe": cat.universe,
            "description": cat.description, "reports": len(dates), "first": dates[0], "latest": dates[-1],
            "latest_count": int(len(latest)), "features": keys,
        })

    # ---------------------------------------------------------------- strategies
    metrics = con.execute("SELECT strategy_id, window_name, metrics FROM strategy_metrics").df()
    metrics_by = {}
    for sid, window, js in metrics.itertuples(index=False):
        metrics_by.setdefault(sid, {})[window] = json.loads(js)
    navs = con.execute("SELECT strategy_id, date, nav, nav_price, positions FROM nav_daily ORDER BY date").df()
    navs["date"] = pd.to_datetime(navs["date"]).dt.date.astype(str)
    bench_nav = {sid.split(".", 1)[1]: g.set_index("date") for sid, g in navs.groupby("strategy_id") if sid.startswith("bench.")}
    trades = con.execute("SELECT * FROM trades ORDER BY entry_date").df()
    for col in ("signal_date", "entry_date", "exit_signal_date", "exit_date"):
        trades[col] = pd.to_datetime(trades[col]).dt.date.astype(str).replace("NaT", None)

    strategy_meta = []
    for strat in load_strategies():
        nav = navs[navs["strategy_id"] == strat.id].set_index("date")
        if nav.empty:
            continue
        dates = list(nav.index)
        benches = ["SPY"] + (["MDY"] if REGISTRY[strat.category].universe == "sp400" else [])
        bench_series = {}
        for b in benches:
            series = bench_nav[b].reindex(dates)
            bench_series[b] = {"nav": [_num(100 * v / series["nav"].iloc[0], 3) for v in series["nav"]],
                               "nav_price": [_num(100 * v / series["nav_price"].iloc[0], 3) for v in series["nav_price"]]}
        t = trades[trades["strategy_id"] == strat.id]
        trade_rows = [[r.ticker, key_of.get(r.security_id, r.ticker), r.signal_date, r.entry_date, _num(r.entry_price, 4),
                       r.exit_date, _num(r.exit_price, 4), r.exit_reason, _num(r.return_total), _num(r.return_price), r.status]
                      for r in t.itertuples(index=False)]
        label = strategy_label(strat)
        sizes[f"strategies/{strat.id}"] = _write(out_dir / "strategies" / f"{strat.id}.json", {
            "id": strat.id, **label, "category": strat.category,
            "start": session_index.get(dates[0]), "nav": [_num(v, 3) for v in nav["nav"]],
            "nav_price": [_num(v, 3) for v in nav["nav_price"]], "positions": [int(v) for v in nav["positions"]],
            "benchmarks": bench_series, "metrics": metrics_by.get(strat.id, {}),
            "trade_fields": ["ticker", "key", "signal", "entry", "entry_px", "exit", "exit_px", "reason",
                             "ret_total", "ret_price", "status"],
            "trades": trade_rows,
        })
        open_now = t[t["status"] == "open"]
        strategy_meta.append({
            "id": strat.id, **label, "category": strat.category, "visible": strat.visible,
            "start": dates[0], "metrics": metrics_by.get(strat.id, {}),
            "holdings": list(dict.fromkeys(key_of.get(s, s) for s in open_now["security_id"])),
            "spark": [_num(v, 2) for v in nav["nav"].iloc[::5]],
        })

    # ---------------------------------------------------------------- stocks
    panel = load_panel(con)
    first_report = min(c["first"] for c in category_meta)
    wl = watchlists.load()
    stock_ids = set(snaps["security_id"]) | {
        sid for sid, tk in key_of.items() if tk in {t for w in wl for t in w.tickers}}
    names = dict(con.execute("SELECT security_id, name FROM securities").fetchall())
    report_pairs = [(str(d), str(a)) for d, a in con.execute(
        "SELECT DISTINCT report_date, as_of FROM category_snapshots WHERE origin = 'backtest' ORDER BY 1").fetchall()]
    congress_payload, hedge_payload, congress, holders = export_smartmoney.build(con, key_of, report_pairs)
    start_ts = pd.Timestamp(first_report) - pd.DateOffset(months=13)
    closes = panel.close.loc[start_ts:]
    stock_index = []
    for sid in sorted(stock_ids):
        key = key_of.get(sid)
        if not key or sid not in closes.columns:
            continue
        series = closes[sid].dropna()
        if series.empty:
            continue
        cats = snaps[snaps["security_id"] == sid]
        appearances = {c: [[d, int(r)] for d, r in zip(g["report_date"], g["rank"])] for c, g in cats.groupby("category_id")}
        t = trades[trades["security_id"] == sid]
        stock_trades = [[r.strategy_id, r.entry_date, r.exit_date, _num(r.return_total), r.status] for r in t.itertuples(index=False)]
        payload = {
            "ticker": key, "name": names.get(sid), "start": session_index.get(series.index[0].date().isoformat()),
            "close": [_num(v, 4) for v in closes[sid].loc[series.index[0]:]],
            "categories": appearances, "trades": stock_trades,
            "congress": congress.get(key, [])[:80],
            "funds": holders.get(key, [])[:25],
            "n_funds": len(holders.get(key, [])),
        }
        sizes[f"stocks/{key}"] = _write(out_dir / "stocks" / f"{key}.json", payload)
        stock_index.append([key, names.get(sid)])

    # ---------------------------------------------------------------- smart money
    sizes["congress"] = _write(out_dir / "congress.json", congress_payload)
    sizes["hedge"] = _write(out_dir / "hedge.json", hedge_payload)

    sizes["meta"] = _write(out_dir / "meta.json", {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "data_through": sessions[-1], "first_report": first_report,
        "categories": category_meta, "strategies": strategy_meta,
        "benchmarks": {k.split(".", 1)[1]: v for k, v in metrics_by.items() if k.startswith("bench.")},
        "windows": list(config()["evaluation"]["windows"]),
        "stocks": stock_index,
        "watchlists": [{"name": w.name, "description": w.description, "options": w.options,
                        "tickers": sorted(w.tickers)} for w in wl],
    })
    con.close()
    return {"files": len(sizes), "bytes": sum(sizes.values()), "stocks": len(stock_index)}


def main() -> None:
    stats = export()
    print(f"{stats['files']} files, {stats['bytes'] / 1e6:.1f} MB ({stats['stocks']} stock pages)")


if __name__ == "__main__":
    main()
