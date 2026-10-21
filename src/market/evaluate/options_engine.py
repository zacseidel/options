"""Evaluate option strategies: base windows → option instrument per window → NAV and metrics.

Each option strategy reuses its base stock strategy's exposure windows (same entries and exits)
from the start of the options history. Windows are equal-capital and rebalanced only when a
window opens or closes, like the stock engine, with each window's value taken from its own
simulated path (continuing windows are rebalanced at their close mark, frictionlessly).

Fills are at the traded price (mid of the day's open and close; no spread haircut). Every base
also gets its stock version over exactly the same windows (`stock_same`), and each option method
records its stock-equivalent exposure at entry and a leverage-aware position size
(half-Kelly ÷ exposure, capped at 100%).
"""

from __future__ import annotations

import time

import pandas as pd

from market.config import config
from market.evaluate.metrics import performance, trade_stats
from market.methods.hold_rules import HOLD_RULES, Trade, fill_price
from market.methods.instruments.options import OptionData, simulate_window
from market.data.options import option_root

FILL_HAIRCUT = 0.0          # trade price; the haircut machinery stays for sensitivity runs


def entry_exposure(data: OptionData, t: Trade, res) -> float | None:
    """Stock-equivalent exposure per unit of capital at entry (1.0 = the stock); None if no option opened."""
    opened = [l for l in res.legs if l.open_date == t.entry_session]
    if not any(l.kind != "S" for l in opened):
        return None
    spot = data.stock_fill(t.security_id, t.entry_session)
    shares = sum(l.qty for l in opened if l.kind == "S")
    return (shares + sum(l.qty * (l.delta or 0.0) for l in opened if l.kind != "S")) * spot


def load_option_data(con, panel) -> OptionData | None:
    bars = con.execute("SELECT session, root, expiry, kind, strike, open, close, volume, transactions FROM option_bars").df()
    if bars.empty:
        return None
    dividends = con.execute("SELECT security_id, ex_date, amount FROM dividends WHERE kind IN ('CD', 'SC')").df()
    cfg = config()
    liq = cfg["options"]["liquidity"]
    liquidity = {"short": liq, "leap": liq.get("leap", {"min_volume": 2, "min_transactions": 1})}
    return OptionData(bars, panel, dividends, cfg["evaluation"]["risk_free_rate"], cfg["options"]["haircut"], liquidity)


def options_start(con, panel) -> pd.Timestamp:
    """First session a window may enter: the session after the first option file (selection needs a prior day)."""
    first = con.execute("SELECT min(session) FROM option_coverage").fetchone()[0]
    return panel.sessions[panel.sessions.searchsorted(pd.Timestamp(first), side="right")]


def nav_from_paths(windows: list[tuple[Trade, object]], sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Equal-capital portfolio of window value paths (each path starts at 1.0 capital)."""
    entries: dict[pd.Timestamp, list[int]] = {}
    exits: dict[pd.Timestamp, list[int]] = {}
    for i, (t, res) in enumerate(windows):
        entries.setdefault(t.entry_session, []).append(i)
        if res.exit_value is not None:
            exits.setdefault(t.exit_session, []).append(i)
    cash, units, active = 100.0, {}, set()
    navs, counts = [], []
    for s in sessions:
        if s in entries or s in exits:
            for i in exits.get(s, []):
                if i in active:
                    cash += units.pop(i, 0.0) * windows[i][1].exit_value
                    active.discard(i)
            new = set(entries.get(s, []))
            active |= new
            if active:
                value_of = {i: 1.0 if i in new else float(windows[i][1].marks.get(s, windows[i][1].marks.iloc[-1]))
                            for i in active}
                total = cash + sum(units.get(i, 0.0) * value_of[i] for i in active)
                target = total / len(active)
                units = {i: target / value_of[i] for i in active if value_of[i] > 0}
                cash = total - sum(units[i] * value_of[i] for i in units)
        nav = cash
        for i, n in units.items():
            marks = windows[i][1].marks
            nav += n * float(marks.get(s, marks.iloc[-1]))
        navs.append(nav)
        counts.append(len(active))
    return pd.DataFrame({"nav": navs, "nav_price": navs, "positions": counts}, index=sessions)


def _summary(nav: pd.Series, rf: float, spy: pd.Series) -> dict:
    p = performance(nav, rf, spy.reindex(nav.index))
    return {k: p.get(k) for k in ("cagr", "total_return", "sharpe", "max_drawdown", "volatility")}


def evaluate_options(con, panel, mult: pd.DataFrame, strategies, base_trades: dict, spy_nav: pd.Series,
                     build_stock_nav) -> dict:
    """strategies: option Strategy objects. base_trades: base id → list[Trade] (already closed out).
    Returns {strategy_id: {"nav", "stats", "trades", "legs"}}."""
    t0 = time.time()
    data = load_option_data(con, panel)
    if data is None or not strategies:
        return {}
    start = options_start(con, panel)
    sessions = panel.sessions[panel.sessions >= start]
    rf = config()["evaluation"]["risk_free_rate"]
    tickers_now = dict(con.execute("SELECT security_id, ticker FROM securities").fetchall())
    out = {}
    stock_same_cache: dict[str, dict] = {}
    for strat in strategies:
        windows = [t for t in base_trades[strat.base] if t.entry_session >= start]
        main = [(t, simulate_window(data, t.security_id, option_root(t.ticker), t.entry_session,
                                    t.exit_session, strat.method, FILL_HAIRCUT)) for t in windows]
        nav = nav_from_paths(main, sessions)
        if strat.base not in stock_same_cache:
            stock_nav = build_stock_nav(windows, start)
            done = [t for t in windows if t.exit_session is not None]
            rets = pd.Series([fill_price(panel, t.exit_session, t.security_id) / fill_price(panel, t.entry_session, t.security_id) - 1
                              for t in done])
            days = pd.Series([(t.exit_session - t.entry_session).days for t in done], dtype=float)
            ts = trade_stats(rets, days, config()["evaluation"]["kelly_min_closed_trades"])
            summary = _summary(stock_nav["nav"], rf, spy_nav)
            summary.update({"half_kelly": ts.get("half_kelly"), "win_rate": ts.get("win_rate"), "stock_equiv": 1.0,
                            "position": ts.get("half_kelly")})
            stock_same_cache[strat.base] = summary
            out[f"{strat.base}.stock_same"] = {"nav": stock_nav, "stats": {}, "trades": None, "legs": None}

        trade_rows, leg_rows = [], []
        n = len(main)
        ev_sum = {k: 0.0 for k in ("option_opens", "no_contract", "assigned", "called_away", "model_fills", "premium", "rolls", "stock_fallback")}
        windows_with = {"options": 0, "assigned": 0, "called_away": 0}
        window_years = 0.0
        exposures = []
        for t, res in main:
            x = entry_exposure(data, t, res)
            if x is not None:
                exposures.append(x)
            trade_id = f"{strat.id}:{t.ticker}:{t.signal_date}:{t.lot}"
            closed = res.exit_value is not None
            value = res.exit_value if closed else float(res.marks.iloc[-1])
            entry_px = fill_price(panel, t.entry_session, t.security_id)
            exit_px = fill_price(panel, t.exit_session, t.security_id) if closed else None
            trade_rows.append({
                "strategy_id": strat.id, "trade_id": trade_id, "security_id": t.security_id, "ticker": t.ticker,
                "signal_date": t.signal_date, "entry_date": t.entry_session.date(), "entry_price": entry_px,
                "exit_signal_date": t.exit_signal_date, "exit_date": t.exit_session.date() if closed else None,
                "exit_price": exit_px, "exit_reason": t.exit_reason,
                "return_price": value - 1, "return_total": value - 1, "status": "closed" if closed else "open",
            })
            for j, leg in enumerate(res.legs):
                leg_rows.append({
                    "strategy_id": strat.id, "trade_id": trade_id, "leg": j, "kind": leg.kind,
                    "side": "long" if leg.qty > 0 else "short",
                    "expiry": leg.contract[1].date() if leg.contract else None,
                    "strike": leg.contract[3] if leg.contract else None,
                    "open_date": leg.open_date.date(), "open_price": leg.open_price,
                    "open_delta": leg.delta, "open_iv": leg.iv,
                    "close_date": leg.close_date.date() if leg.close_date is not None else None,
                    "close_price": leg.close_price, "close_reason": leg.close_reason, "quantity": abs(leg.qty),
                })
            for k in ev_sum:
                ev_sum[k] += res.events[k]
            windows_with["options"] += res.events["option_opens"] > 0
            windows_with["assigned"] += res.events["assigned"] > 0
            windows_with["called_away"] += res.events["called_away"] > 0
            window_years += max(len(res.marks), 1) / 252

        frame = pd.DataFrame(trade_rows)
        closed = frame[frame["status"] == "closed"] if n else frame
        hold_days = (pd.to_datetime(closed["exit_date"]) - pd.to_datetime(closed["entry_date"])).dt.days if n else pd.Series(dtype=float)
        stats = trade_stats(closed["return_total"], hold_days, config()["evaluation"]["kelly_min_closed_trades"]) if n else {}
        exposure = float(pd.Series(exposures).median()) if exposures else None
        hk = stats.get("half_kelly")
        stats.update({
            "tier": strat.method.get("tier"),
            "stock_equiv": round(exposure, 4) if exposure is not None else None,
            "position": round(min(1.0, hk / exposure), 4) if hk is not None and exposure else None,
            "stock_fallback": int(ev_sum["stock_fallback"]),
            "open_trades": int((frame["status"] == "open").sum()) if n else 0,
            "exposure": round(float((nav["positions"] > 0).mean()), 4),
            "windows": n,
            "option_coverage": round(windows_with["options"] / n, 4) if n else None,
            "assignment_rate": round(windows_with["assigned"] / n, 4) if n else None,
            "called_away_rate": round(windows_with["called_away"] / n, 4) if n else None,
            "model_fills": int(ev_sum["model_fills"]),
            "missed_selections": int(ev_sum["no_contract"]),
            "rolls": int(ev_sum["rolls"]),
            "premium_yield": round(ev_sum["premium"] / window_years, 4) if window_years else None,
            "stock_same": stock_same_cache[strat.base],
        })
        out[strat.id] = {"nav": nav, "stats": stats, "trades": frame, "legs": pd.DataFrame(leg_rows)}
        print(f"  {strat.id}: {n} windows, {time.time() - t0:.0f}s", flush=True)
    return out
