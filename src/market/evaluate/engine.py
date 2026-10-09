"""Evaluate strategies: snapshots → trades (hold rule) → NAV → metrics, stored in DuckDB.

Portfolio policy (as in the eval repo): equal weight per open trade, rebalanced only on
sessions where a trade opens or closes, at that session's fill prices; marked daily at the
close. Two bases are kept side by side: price return and total return (dividends
reinvested). Idle cash earns nothing (conservative; noted in the methodology).

Usage:  python -m market.evaluate.engine [--strategy ID ...]
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime

import duckdb

import pandas as pd
import yaml

from market.config import ROOT, config
from market.evaluate.metrics import performance, trade_stats
from market.methods.hold_rules import HOLD_RULES, Trade, fill_price
from market.store.db import connect, replace_rows
from market.store.panel import Panel, load_panel

STALE_DAYS = 7          # a holding with no bar for this long is treated as delisted


@dataclass(frozen=True)
class Strategy:
    id: str
    category: str
    slot: object
    hold: str
    params: dict
    instrument: str
    visible: bool


def load_strategies(path=None) -> list[Strategy]:
    raw = yaml.safe_load((path or ROOT / "strategies.yaml").read_text())
    defaults = raw.get("defaults") or {}
    out = []
    for spec in raw["strategies"]:
        spec = {**defaults, **spec}
        out.append(Strategy(spec["id"], spec["category"], spec["slot"], spec["hold"],
                            spec.get("params") or {}, spec["instrument"], spec.get("visible", True)))
    return out


def dividend_multiplier(panel: Panel) -> pd.DataFrame:
    """m[t] such that price × m is in total-return terms (dividends reinvested)."""
    first_close = panel.close.bfill().iloc[0]
    return panel.tr / (panel.close / first_close)


def close_out_delisted(trades: list[Trade], panel: Panel) -> None:
    """Open trades whose security stopped trading are closed at its last bar (acquisition/delisting)."""
    end = panel.sessions[-1]
    for trade in trades:
        if trade.exit_session is not None:
            continue
        last = panel.close[trade.security_id].dropna().index[-1]
        if (end - last).days > STALE_DAYS:
            trade.exit_session, trade.exit_reason = last, "delisted (last bar)"


def trade_frame(strategy: Strategy, trades: list[Trade], panel: Panel, mult: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t in trades:
        entry_px = fill_price(panel, t.entry_session, t.security_id)
        closed = t.exit_session is not None
        if closed:
            exit_px = (float(panel.close.at[t.exit_session, t.security_id]) if t.exit_reason == "delisted (last bar)"
                       else fill_price(panel, t.exit_session, t.security_id))
            mark_session = t.exit_session
        else:
            mark_session = panel.close[t.security_id].dropna().index[-1]
            exit_px = float(panel.close.at[mark_session, t.security_id])
        m_in, m_out = mult.at[t.entry_session, t.security_id], mult.at[mark_session, t.security_id]
        rows.append({
            "strategy_id": strategy.id,
            "trade_id": f"{strategy.id}:{t.ticker}:{t.signal_date}:{t.lot}",
            "security_id": t.security_id, "ticker": t.ticker, "signal_date": t.signal_date,
            "entry_date": t.entry_session.date(), "entry_price": entry_px,
            "exit_signal_date": t.exit_signal_date, "exit_date": t.exit_session.date() if closed else None,
            "exit_price": exit_px if closed else None, "exit_reason": t.exit_reason,
            "return_price": exit_px / entry_px - 1,
            "return_total": (exit_px * m_out) / (entry_px * m_in) - 1,
            "status": "closed" if closed else "open",
            "_mark_date": mark_session.date(), "_mark_price": exit_px,
        })
    return pd.DataFrame(rows)


def build_nav(trades: list[Trade], panel: Panel, mult: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Daily NAV (start 100) on price and total-return bases."""
    sessions = panel.sessions[panel.sessions >= start]
    entries: dict[pd.Timestamp, list[int]] = {}
    exits: dict[pd.Timestamp, list[int]] = {}
    for i, t in enumerate(trades):
        entries.setdefault(t.entry_session, []).append(i)
        if t.exit_session is not None:
            exits.setdefault(t.exit_session, []).append(i)
    marks = panel.close.ffill(limit=STALE_DAYS)
    out = {}
    for basis in ("price", "total"):
        cash, shares, active = 100.0, {}, set()
        series, counts = [], []
        for s in sessions:
            m = mult.loc[s] if basis == "total" else None
            px = lambda sid, value: value * (m[sid] if m is not None else 1.0)      # noqa: E731
            if s in entries or s in exits:
                for i in exits.get(s, []):
                    if i in active:
                        t = trades[i]
                        raw = (panel.close.at[s, t.security_id] if t.exit_reason == "delisted (last bar)"
                               else fill_price(panel, s, t.security_id))
                        cash += shares.pop(i) * px(t.security_id, raw)
                        active.discard(i)
                active |= set(entries.get(s, []))
                if active:
                    exec_px = {i: px(trades[i].security_id, fill_price(panel, s, trades[i].security_id)) for i in active}
                    value = cash + sum(shares.get(i, 0.0) * exec_px[i] for i in active)
                    target = value / len(active)
                    shares = {i: target / exec_px[i] for i in active}
                    cash = 0.0
            nav = cash + sum(n * px(trades[i].security_id, marks.at[s, trades[i].security_id]) for i, n in shares.items())
            series.append(nav)
            counts.append(len(active))
        out[basis] = series
    return pd.DataFrame({"nav": out["total"], "nav_price": out["price"], "positions": counts}, index=sessions)


def benchmark_navs(con: duckdb.DuckDBPyConnection, panel: Panel, mult: pd.DataFrame, start: pd.Timestamp) -> dict:
    ids = dict(con.execute(
        f"SELECT ticker, security_id FROM securities WHERE type = 'ETF' AND ticker IN "
        f"({','.join('?' * len(config()['evaluation']['benchmarks']))})", config()["evaluation"]["benchmarks"]
    ).fetchall())
    navs = {}
    for ticker, sid in ids.items():
        close = panel.close.loc[start:, sid]
        total = close * mult.loc[start:, sid]
        navs[ticker] = pd.DataFrame({"nav": 100 * total / total.iloc[0], "nav_price": 100 * close / close.iloc[0],
                                     "positions": 1})
    return navs


def window_slices(nav: pd.Series, windows: dict) -> dict[str, pd.Series]:
    out = {}
    for name, years in windows.items():
        if years is None:
            out[name] = nav
        else:
            cutoff = nav.index[-1] - pd.DateOffset(years=years)
            if nav.index[0] <= cutoff:
                out[name] = nav[nav.index >= cutoff]
    return out


def evaluate(strategy_ids: list[str] | None = None) -> dict:
    t0 = time.time()
    con = connect()
    panel = load_panel(con)
    mult = dividend_multiplier(panel)
    cfg = config()["evaluation"]
    strategies = [s for s in load_strategies() if not strategy_ids or s.id in strategy_ids]
    starts, summary = [], {}

    for strat in strategies:
        snaps = con.execute(
            "SELECT report_date, security_id, ticker, rank FROM category_snapshots "
            "WHERE category_id = ? AND origin = 'backtest' ORDER BY report_date, rank", [strat.category]
        ).df()
        snaps["report_date"] = pd.to_datetime(snaps["report_date"]).dt.date
        trades = HOLD_RULES[strat.hold](snaps, panel, strat.slot, strat.params)
        close_out_delisted(trades, panel)
        start = panel.session_on_or_after(min(snaps["report_date"]))
        starts.append(start)
        frame = trade_frame(strat, trades, panel, mult)
        nav = build_nav(trades, panel, mult, start)

        closed = frame[frame["status"] == "closed"]
        hold_days = (pd.to_datetime(closed["exit_date"]) - pd.to_datetime(closed["entry_date"])).dt.days
        stats = trade_stats(closed["return_total"], hold_days, cfg["kelly_min_closed_trades"])
        stats["open_trades"] = int((frame["status"] == "open").sum())
        stats["exposure"] = round(float((nav["positions"] > 0).mean()), 4)

        replace_rows(con, "trades", frame.drop(columns=["_mark_date", "_mark_price"]), "strategy_id = ?", [strat.id])
        replace_rows(con, "nav_daily", nav.reset_index(names="date").assign(strategy_id=strat.id)[
            ["strategy_id", "date", "nav", "nav_price", "positions"]], "strategy_id = ?", [strat.id])
        summary[strat.id] = {"nav": nav, "stats": stats}

    bench = benchmark_navs(con, panel, mult, min(starts))
    for ticker, nav in bench.items():
        replace_rows(con, "nav_daily", nav.reset_index(names="date").assign(strategy_id=f"bench.{ticker}")[
            ["strategy_id", "date", "nav", "nav_price", "positions"]], "strategy_id = ?", [f"bench.{ticker}"])

    now = datetime.now()
    metric_rows = []
    for sid, info in {**summary, **{f"bench.{t}": {"nav": n, "stats": {}} for t, n in bench.items()}}.items():
        nav = info["nav"]["nav"]
        for name, part in window_slices(nav, cfg["windows"]).items():
            spy = bench["SPY"]["nav"].reindex(part.index)
            row = performance(part, cfg["risk_free_rate"], None if sid == "bench.SPY" else spy)
            row["price_return"] = float(info["nav"]["nav_price"].reindex(part.index).iloc[-1]
                                        / info["nav"]["nav_price"].reindex(part.index).iloc[0] - 1)
            if name == "all":
                row.update(info["stats"])
            metric_rows.append({"strategy_id": sid, "window_name": name, "metrics": json.dumps(row), "computed_at": now})
    ids = [r["strategy_id"] for r in metric_rows]
    replace_rows(con, "strategy_metrics", pd.DataFrame(metric_rows),
                 f"strategy_id IN ({','.join('?' * len(set(ids)))})", sorted(set(ids)))
    con.close()
    return {"seconds": round(time.time() - t0, 1), "strategies": len(strategies)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strategy", nargs="+")
    args = parser.parse_args()
    print(evaluate(args.strategy))


if __name__ == "__main__":
    main()

