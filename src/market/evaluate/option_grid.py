"""Option method grid: every candidate option method on every option base, over the options history.

A research tool for choosing which methods to track (strategies.yaml `option_methods`), meant to be
re-run periodically. It reads the store read-only, so it can run beside the daily pipeline, and
writes docs/options_grid.md plus data/options_grid.json.

All fills are at the traded price (mid of the day's open and close; no spread haircut). Columns:
  CAGR / total  compound annual growth and total return of the equal-capital NAV (simple returns)
  Sharpe        the site's: mean daily log excess return / stdev × √252
  half-Kelly    the site's per-trade 0.5 · (p − q / b) over the method's closed windows
  position      half-Kelly ÷ exposure, capped at 100%: the share of a portfolio per position once
                the method's leverage is counted (half-Kelly alone ignores it — doubling every win
                and loss leaves p and b unchanged)
  exposure      median stock-equivalent exposure at entry (1.0× = the stock; Σ qty·Δ·spot / capital)
  no option     share of windows that never found a qualifying contract (LEAP/diagonal hold the stock
                until one appears)

    python -m market.evaluate.option_grid [base ...]
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

LEAP_EXPIRIES = {
    "6m": {"min": 180, "max": 365, "prefer": 180, "roll_below": 120},
    "12m": {"min": 365, "max": 600, "prefer": 365, "roll_below": 180},
}
SIZINGS = {"delta": "match stock", 0.5: "50% in calls", 1.0: "100% in calls"}
COVERED_CALL_DTE = {"short_dte": [14, 28], "short_prefer": 21}


def methods_for(base_short_dte: list[int]) -> list[dict]:
    """The candidate grid. Each entry: group, name, and the instrument method dict."""
    out = [{"group": "Stock", "name": "Stock (same windows)", "method": None}]
    for d in (-0.20, -0.30, -0.45):
        out.append({"group": "Lower risk", "name": f"Cash-secured put Δ{d:.2f}",
                    "method": {"instrument": "csp", "delta": d, "short_dte": base_short_dte}})
    for d in (0.10, 0.20, 0.30, 0.40, 0.50):
        out.append({"group": "Lower risk", "name": f"Covered call Δ{d:.2f}, ~21d",
                    "method": {"instrument": "covered_call", "delta": d, **COVERED_CALL_DTE}})
    for e, ld in LEAP_EXPIRIES.items():
        for long_d in (0.80,):
            for short_d in (0.20, 0.30):
                out.append({"group": "Lower risk", "name": f"Diagonal {e} Δ{long_d:.2f} / short Δ{short_d:.2f}",
                            "method": {"instrument": "diagonal", "delta": long_d, "short_delta": short_d,
                                       "sizing": "delta", "delta_tol": 0.05, "fallback": "stock",
                                       "leap_dte": ld, **COVERED_CALL_DTE}})
    for sizing, label in SIZINGS.items():
        group = "Same risk" if sizing == "delta" else "Higher risk"
        for e, ld in LEAP_EXPIRIES.items():
            for d in (0.80, 0.60):
                out.append({"group": group, "name": f"LEAP {e} Δ{d:.2f}, {label}",
                            "method": {"instrument": "leap", "delta": d, "sizing": sizing, "delta_tol": 0.05,
                                       "fallback": "stock", "leap_dte": ld, "short_dte": base_short_dte}})
    return out


def run_base(base_id: str) -> dict:
    import duckdb

    from market.config import config, path
    from market.data.options import option_root
    from market.evaluate.engine import build_nav, close_out_delisted, dividend_multiplier, load_strategies
    from market.evaluate.metrics import performance, trade_stats
    from market.evaluate.options_engine import entry_exposure, load_option_data, nav_from_paths, options_start
    from market.methods.hold_rules import HOLD_RULES, fill_price
    from market.methods.instruments.options import simulate_window
    from market.store.panel import load_panel

    t0 = time.time()
    con = duckdb.connect(str(path("db")), read_only=True)
    panel = load_panel(con)
    mult = dividend_multiplier(panel)
    cfg = config()["evaluation"]
    strategies = {s.id: s for s in load_strategies()}
    base = strategies[base_id]
    data = load_option_data(con, panel)
    start = options_start(con, panel)
    sessions = panel.sessions[panel.sessions >= start]
    snaps = con.execute(
        "SELECT report_date, security_id, ticker, rank FROM category_snapshots "
        "WHERE category_id = ? AND origin = 'backtest' ORDER BY report_date, rank", [base.category]).df()
    snaps["report_date"] = pd.to_datetime(snaps["report_date"]).dt.date
    trades = HOLD_RULES[base.hold](snaps, panel, base.slot, base.params)
    close_out_delisted(trades, panel)
    windows = [t for t in trades if t.entry_session >= start]
    import yaml
    from market.config import ROOT
    spec = yaml.safe_load((ROOT / "strategies.yaml").read_text())["option_methods"]["short_dte"]
    short_dte = spec.get(base_id, spec["default"])

    def summarize(nav: pd.Series, returns: pd.Series, hold_days: pd.Series) -> dict:
        p = performance(nav, cfg["risk_free_rate"])
        ts = trade_stats(returns, hold_days, cfg["kelly_min_closed_trades"])
        return {"cagr": p["cagr"], "total_return": p["total_return"], "volatility": p["volatility"],
                "sharpe": p["sharpe"], "max_drawdown": p["max_drawdown"], "half_kelly": ts.get("half_kelly"),
                "win_rate": ts.get("win_rate")}

    closed = [t for t in windows if t.exit_session is not None]
    hold_days = pd.Series([(t.exit_session - t.entry_session).days for t in closed], dtype=float)
    rows = []
    for spec in methods_for(short_dte):
        if spec["method"] is None:
            nav = build_nav(windows, panel, mult, start)["nav"]
            rets = pd.Series([fill_price(panel, t.exit_session, t.security_id) / fill_price(panel, t.entry_session, t.security_id) - 1
                              for t in closed])
            row = summarize(nav, rets, hold_days)
            row.update({"exposure": 1.0, "no_option": None, "model_fills": None, "dte": None})
        else:
            runs = [(t, simulate_window(data, t.security_id, option_root(t.ticker), t.entry_session, t.exit_session,
                                        spec["method"], 0.0)) for t in windows]
            nav = nav_from_paths(runs, sessions)["nav"]
            rets = pd.Series([r.exit_value - 1 for t, r in runs if r.exit_value is not None])
            row = summarize(nav, rets, hold_days)
            exposures = [x for x in (entry_exposure(data, t, r) for t, r in runs) if x is not None]
            options = [l for _, r in runs for l in r.legs if l.kind != "S"]
            row.update({
                "exposure": float(np.median(exposures)) if exposures else None,
                "no_option": sum(r.events["option_opens"] == 0 for _, r in runs) / len(runs),
                "model_fills": sum(r.events["model_fills"] for _, r in runs) / len(runs),
                "dte": float(np.median([(l.contract[1] - l.open_date).days for l in options])) if options else None,
            })
        if row.get("half_kelly") is not None and row.get("exposure"):
            row["position"] = min(1.0, row["half_kelly"] / row["exposure"])
        else:
            row["position"] = None
        rows.append({"group": spec["group"], "name": spec["name"], "method": spec["method"],
                     **{k: (None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v))
                        for k, v in row.items()}})
    con.close()
    return {"base": base_id, "windows": len(windows), "start": str(start.date()),
            "end": str(sessions[-1].date()), "seconds": round(time.time() - t0), "rows": rows}


def _pct(v, digits=0):
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def to_markdown(results: list[dict], names: dict) -> str:
    lines = ["# Option method grid", "",
             f"Options history {results[0]['start']} → {results[0]['end']}. Fills at the traded price "
             "(mid of the day's open and close), no spread haircut. Regenerate with "
             "`python -m market.evaluate.option_grid`.", "",
             "Exposure is stock-equivalent at entry (1.0× = holding the stock). Half-Kelly is the site's "
             "per-trade 0.5 · (win rate − loss rate / payoff); Position = half-Kelly ÷ exposure (cap 100%), "
             "the share of a portfolio per position once leverage is counted. "
             "LEAP/diagonal windows hold the stock until a qualifying call appears ('no option' = never).", ""]
    for res in results:
        lines += [f"## {names.get(res['base'], res['base'])} (`{res['base']}`, {res['windows']} windows)", "",
                  "| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in res["rows"]:
            lines.append(f"| {r['group']} | {r['name']} | {_pct(r['cagr'])} | {_pct(r['total_return'])} | "
                         f"{r['sharpe']:.2f} | {_pct(r['max_drawdown'])} | {_pct(r['half_kelly'])} | "
                         f"{r['exposure']:.2f}× | {_pct(r['position'])} | {_pct(r['no_option'])} | "
                         f"{'—' if r['dte'] is None else int(r['dte'])} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    from market.config import ROOT
    from market.evaluate.engine import load_strategies

    strategies = load_strategies()
    bases = argv or list(dict.fromkeys(s.base for s in strategies if s.base))
    with ProcessPoolExecutor(max_workers=len(bases)) as pool:
        results = list(pool.map(run_base, bases))
    names = {s.id: s.id for s in strategies}
    (ROOT / "data" / "options_grid.json").write_text(json.dumps(results, indent=1))
    (ROOT / "docs" / "options_grid.md").write_text(to_markdown(results, names))
    for r in results:
        print(f"{r['base']}: {len(r['rows'])} methods, {r['seconds']}s")


if __name__ == "__main__":
    main(sys.argv[1:])
