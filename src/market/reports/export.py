"""Export the static site's JSON (site/data/), regenerated each run and never versioned.

Layout (small files, loaded per page):
  meta.json                 categories, strategies (+ metrics per window), benchmarks, report dates
  sessions.json             the trading-session calendar shared by every series
  decisions.json            the personal position log (positions.md) priced vs SPY
  categories/<id>.json      full report history for one category (any report / diff is derived in the browser)
  strategies/<id>.json      NAV (total + price) with aligned benchmarks, trades
  stocks/<TICKER>.json      closes, category history, strategy trades, Congress and 13F context
  congress.json             Congress members, trades and leaderboards per report date
  hedge.json                13F funds, filings (new buys / exits) and leaderboards per report date
  members/<id>.json, funds/<cik>.json   profiles of members / funds ever ranked top 25

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
from market.categories.families import FAMILIES, SECTIONS, variant
from market.categories.registry import REGISTRY
from market.config import config, directory
from market.reports import export_decisions, export_newsfeed, export_options, export_profiles, export_smartmoney, site_lock
from market.data import watchlists
from market.evaluate import champions
from market.evaluate.engine import load_strategies
from market.research import lead_time
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
    "ivinverted_sp900": ["term", "iv_rv", "rv20"],
    "mom12iv_sp500": ["return_12m", "iv_rv", "rank_change"],
    "mom12iv_sp400": ["return_12m", "iv_rv", "rank_change"],
    "rankmomiv_sp500": ["avg_rank", "return_3m", "return_12m", "iv_rv"],
    "fmom_sp500": ["gross_margin_chg", "op_margin_chg", "ni_ttm_yoy", "rev_yoy_q"],
    "fmom_sp400": ["gross_margin_chg", "op_margin_chg", "ni_ttm_yoy", "rev_yoy_q"],
    "emerging_sp400": ["fmom", "rank_12m", "rank_change", "op_margin_chg"],
    "emergingall_sp400": ["fmom", "rank_12m", "rank_change", "op_margin_chg"],
    "rerating_sp500": ["ps_chg", "ps", "ni_ttm_yoy", "rev_ttm_yoy"],
    "shrinkers_sp500": ["shares_yoy", "buybacks_ttm", "fcf_margin"],
    "divraise_sp900": ["raise"],
    "divcut_sp900": ["cut"],
    "steady_sp500": ["longevity", "rank_12m", "return_12m"],
    "mom12si_sp500": ["return_12m", "days_to_cover", "rank_change"],
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


_LOCK: site_lock.Lock | None = None          # set by export() when a site pass phrase is configured


def _write(target, payload) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(payload), separators=(",", ":"), default=str, allow_nan=False)
    if _LOCK is not None:
        text = _LOCK.seal_text(text)
    target.write_text(text)
    return len(text)


def strategy_label(strategy) -> dict:
    """Display names: `name` is the short one ("SPY Ldrs · SI", plus "#6–10" for a lower slot), `full` the long one."""
    cat = REGISTRY[strategy.category]
    short = variant(strategy.category).short
    slot = "all signals" if strategy.slot == "all" else (
        f"top {strategy.slot[1]}" if strategy.slot[0] == 1 else f"ranks {strategy.slot[0]}–{strategy.slot[1]}")
    name = short if strategy.slot == "all" or strategy.slot[0] == 1 else f"{short} #{strategy.slot[0]}–{strategy.slot[1]}"
    hold = HOLD_LABELS[strategy.hold].format(**{k: str(v).upper() if k == "indicator" else v
                                                for k, v in strategy.params.items()})
    common = {"slot": slot, "hold": hold, "full": f"{cat.name} · {slot}", "family": variant(strategy.category).family,
              "filter": variant(strategy.category).filter}
    if strategy.instrument == "short":
        return {**common, "name": f"{name} · short", "instrument": f"short (borrow {strategy.method['borrow']:.1%}/yr)"}
    if strategy.instrument == "overlay":
        m = strategy.method
        hedge = f"+ {m['weight']:.0%} short {variant(m['short_category']).short}"
        return {**common, "name": f"{name} {hedge}", "instrument": f"long, {hedge} (see the two strategies for trades)"}
    if strategy.instrument != "stock":
        return {**common, "name": f"{name} · {strategy.method['label']}", "instrument": strategy.method["label"],
                "options": True, "base": strategy.base}
    return {**common, "name": name, "instrument": strategy.instrument}


def current_tickers(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(con.execute("SELECT security_id, ticker FROM securities").fetchall())


def export() -> dict:
    global _LOCK
    out_dir = directory("site_out")
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    # Whole-site lock (market.reports.site_lock): every data file is encrypted; lock.json stays public.
    _LOCK = site_lock.from_env()
    if _LOCK is not None:
        (out_dir / "lock.json").write_text(json.dumps(_LOCK.manifest()))
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
    skipped = con.execute("SELECT category_id, report_date, security_id, ticker, base_rank, reason FROM category_exclusions "
                          "WHERE origin = 'backtest' ORDER BY category_id, report_date, base_rank").df()
    skipped["report_date"] = pd.to_datetime(skipped["report_date"]).dt.date.astype(str)
    skipped_by = {c: g for c, g in skipped.groupby("category_id")}
    category_meta = []
    lead_times = lead_time.compute(con)
    order = {cat_id: i for i, cat_id in enumerate(REGISTRY)}
    for cat_id, frame in sorted(snaps.groupby("category_id"), key=lambda item: order.get(item[0], 99)):
        cat = REGISTRY[cat_id]
        dates = sorted(frame["report_date"].unique())
        index = {d: i for i, d in enumerate(dates)}
        keys = KEY_FEATURES.get(cat_id, [])
        filtered = variant(cat_id).filter is not None
        rows = []
        for r in frame.itertuples(index=False):
            feats = json.loads(r.features)
            rows.append([index[r.report_date], r.ticker, key_of.get(r.security_id, r.ticker), int(r.rank),
                         _num(r.score)] + [feats.get(k) if isinstance(feats.get(k), str) else _num(feats.get(k)) for k in keys]
                        + ([_num(feats.get("base_rank"))] if filtered else []))
        sk = skipped_by.get(cat_id)
        sizes[f"categories/{cat_id}"] = _write(out_dir / "categories" / f"{cat_id}.json", {
            "id": cat_id, "dates": dates, "fields": ["d", "ticker", "key", "rank", "score", *keys] + (["base_rank"] if filtered else []),
            "rows": rows,
            # Names the filter skipped: [report index, ticker, key, position in the base ranking, reason]
            "skipped": [] if sk is None else [[index[d], t, key_of.get(sid, t), int(b), why]
                                              for d, sid, t, b, why in zip(sk["report_date"], sk["security_id"], sk["ticker"],
                                                                           sk["base_rank"], sk["reason"]) if d in index],
        })
        latest = frame[frame["report_date"] == dates[-1]]
        category_meta.append({
            "id": cat_id, "name": cat.name, "short": variant(cat_id).short, "family": variant(cat_id).family,
            "filter": variant(cat_id).filter, "group": cat.group, "universe": cat.universe,
            "description": cat.description, "reports": len(dates), "first": dates[0], "latest": dates[-1],
            "latest_count": int(len(latest)), "features": keys,
            "lead_time": lead_times.get(cat_id),
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
    legs = con.execute("SELECT * FROM option_legs ORDER BY strategy_id, trade_id, leg").df()
    for col in ("expiry", "open_date", "close_date"):
        legs[col] = pd.to_datetime(legs[col]).dt.date.astype(str).replace("NaT", None)
    legs_by = {tid: g for tid, g in legs.groupby("trade_id")}
    for col in ("signal_date", "entry_date", "exit_signal_date", "exit_date"):
        trades[col] = pd.to_datetime(trades[col]).dt.date.astype(str).replace("NaT", None)

    strategy_meta = []
    for strat in load_strategies():
        if strat.stage == "retired":
            continue
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
        extra = {}
        if strat.instrument not in ("stock", "short", "overlay"):
            extra["leg_fields"] = ["kind", "side", "expiry", "strike", "open", "open_px", "delta", "iv",
                                   "close", "close_px", "reason", "qty"]
            extra["legs"] = [[[g.kind, g.side, g.expiry, _num(g.strike, 2), g.open_date, _num(g.open_price, 4),
                               _num(g.open_delta, 3), _num(g.open_iv, 3), g.close_date, _num(g.close_price, 4),
                               g.close_reason, _num(g.quantity, 6)] for g in legs_by[r.trade_id].itertuples(index=False)]
                             if r.trade_id in legs_by else [] for r in t.itertuples(index=False)]
        sizes[f"strategies/{strat.id}"] = _write(out_dir / "strategies" / f"{strat.id}.json", {
            **extra,
            "id": strat.id, **label, "category": strat.category, "stage": strat.stage,
            "added": strat.added.isoformat() if strat.added else None,
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
            "stage": strat.stage, "added": strat.added.isoformat() if strat.added else None,
            "start": dates[0], "metrics": metrics_by.get(strat.id, {}),
            "holdings": list(dict.fromkeys(key_of.get(s, s) for s in open_now["security_id"])),
            "spark": [_num(v, 2) for v in nav["nav"].iloc[::5]],
        })

    # ---------------------------------------------------------------- options page
    panel = load_panel(con)
    all_strategies = load_strategies()
    stock_strategy_ids = {s.id for s in all_strategies if s.instrument == "stock"}
    sizes["options"] = _write(out_dir / "options.json", export_options.build(
        con, panel, all_strategies, metrics_by, navs, session_index, key_of, strategy_label))

    # ---------------------------------------------------------------- newsfeed
    metrics_all, nav_wide = champions.load_inputs(con, all_strategies)
    families = champions.update_feed(con, champions.compute(con, all_strategies, metrics_all, nav_wide))
    sizes["news"] = _write(out_dir / "news.json", export_newsfeed.build(con, panel, key_of, families))
    sizes["decisions"] = _write(out_dir / "decisions.json", export_decisions.build(con, panel, key_of))

    # ---------------------------------------------------------------- stocks
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
        t = trades[(trades["security_id"] == sid) & trades["strategy_id"].isin(stock_strategy_ids)]
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
    members = export_profiles.member_profiles(con, panel, key_of)
    funds = export_profiles.fund_profiles(con, key_of)
    for mid, payload in members.items():
        sizes[f"members/{mid}"] = _write(out_dir / "members" / f"{mid}.json", payload)
    for cik, payload in funds.items():
        sizes[f"funds/{cik}"] = _write(out_dir / "funds" / f"{cik}.json", payload)
    congress_payload["profiles"] = sorted(members)
    congress_payload["data_start"] = next(iter(members.values()))["data_start"] if members else None
    hedge_payload["profiles"] = sorted(funds)
    hedge_payload["data_start"] = next(iter(funds.values()))["data_start"] if funds else None
    sizes["congress"] = _write(out_dir / "congress.json", congress_payload)
    sizes["hedge"] = _write(out_dir / "hedge.json", hedge_payload)

    sizes["meta"] = _write(out_dir / "meta.json", {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "data_through": sessions[-1], "first_report": first_report,
        "categories": category_meta, "strategies": strategy_meta,
        "sections": SECTIONS,
        "families": [{"id": f.id, "name": f.name, "short": f.short, "section": f.section, "base": f.base,
                      **{k: v for k, v in families.get(f.id, {}).items() if k != "family"}} for f in FAMILIES.values()],
        "feed": {k: config()["newsfeed"][k] for k in ("margin_in", "margin_out", "champion_tie")},
        "benchmarks": {k.split(".", 1)[1]: v for k, v in metrics_by.items() if k.startswith("bench.")},
        "windows": list(config()["evaluation"]["windows"]),
        "stocks": stock_index,
        "profiles": {"congress": sorted(members), "hedge": sorted(funds)},
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
