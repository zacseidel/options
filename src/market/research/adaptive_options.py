"""Adaptive option tier: which implied-volatility rule should choose between a base's option methods?

For each option base, every window is simulated once under each of its three tracked methods
(Defensive / Balanced / Aggressive). A candidate rule then picks, per window, from the IV reading on
the selection day (`market.methods.adaptive`): rich → the Defensive put, cheap → the Aggressive calls,
otherwise → Balanced. Each candidate's equal-capital NAV is scored on the first half of the options
history (choose) and the second (check), next to the three fixed tiers.

Pre-set choice: ONE rule for all bases — the candidate with the best average in-sample Sharpe rank
across bases — so the choice isn't fitted base by base.

Usage:  python -m market.research.adaptive_options
"""

from __future__ import annotations

import argparse
import itertools

import numpy as np
import pandas as pd

from market.config import config
from market.evaluate.engine import close_out_delisted, load_strategies
from market.evaluate.metrics import performance
from market.evaluate.options_engine import load_option_data, nav_from_paths, options_start, simulate
from market.methods.adaptive import IvSignal, branch
from market.methods.hold_rules import HOLD_RULES
from market.research.common import write_report
from market.store.db import connect
from market.store.panel import load_panel

TIER_FOR = {"when_rich": "Defensive", "when_cheap": "Aggressive", "otherwise": "Balanced"}
CANDIDATES = (
    [{"signal": "ratio", "rich": r, "cheap": c} for r, c in itertools.product((1.1, 1.2, 1.3, 1.5), (0.8, 0.9, 1.0)) if c < r]
    + [{"signal": "pct", "rich": r, "cheap": c} for r, c in itertools.product((0.6, 0.7, 0.8), (0.2, 0.3, 0.4))]
)


def _score(nav: pd.Series, split: pd.Timestamp, rf: float) -> dict:
    out = {}
    for label, part in (("in", nav[nav.index < split]), ("out", nav[nav.index >= split]), ("all", nav)):
        if len(part) < 20:
            out[label] = {"cagr": None, "sharpe": None, "max_drawdown": None}
            continue
        p = performance(part / part.iloc[0] * 100, rf)
        out[label] = {k: p.get(k) for k in ("cagr", "sharpe", "max_drawdown")}
    return out


def run() -> dict:
    con = connect()
    panel = load_panel(con)
    data = load_option_data(con, panel)
    signal = IvSignal(con, panel)
    start = options_start(con, panel)
    sessions = panel.sessions[panel.sessions >= start]
    split = sessions[len(sessions) // 2]
    rf = config()["evaluation"]["risk_free_rate"]
    strategies = load_strategies()
    by_id = {s.id: s for s in strategies}
    results = {}
    for base_id in dict.fromkeys(s.base for s in strategies if s.base):
        base = by_id[base_id]
        tiers = {s.method["tier"]: s for s in strategies
                 if s.base == base_id and s.instrument != "adaptive" and s.method.get("tier") in TIER_FOR.values()}
        snaps = con.execute("SELECT report_date, security_id, ticker, rank FROM category_snapshots "
                            "WHERE category_id = ? AND origin = 'backtest' ORDER BY report_date, rank",
                            [base.category]).df()
        snaps["report_date"] = pd.to_datetime(snaps["report_date"]).dt.date
        trades = HOLD_RULES[base.hold](snaps, panel, base.slot, base.params)
        close_out_delisted(trades, panel)
        windows = [t for t in trades if t.entry_session >= start]
        sims = {tier: [simulate(data, t, s.method)[0] for t in windows] for tier, s in tiers.items()}
        readings = {kind: [signal.at(t.security_id, t.entry_session, kind) for t in windows] for kind in ("ratio", "pct")}
        rows = []
        for tier in ("Defensive", "Balanced", "Aggressive"):
            nav = nav_from_paths(list(zip(windows, sims[tier])), sessions)["nav"]
            rows.append({"rule": f"fixed: {tier}", **_score(nav, split, rf), "mix": None})
        for cand in CANDIDATES:
            picks = [TIER_FOR[branch(cand, v)] for v in readings[cand["signal"]]]
            runs = [(t, sims[p][i]) for i, (t, p) in enumerate(zip(windows, picks))]
            nav = nav_from_paths(runs, sessions)["nav"]
            mix = pd.Series(picks).value_counts(normalize=True).round(2).to_dict()
            rows.append({"rule": f"{cand['signal']} rich≥{cand['rich']:g} cheap≤{cand['cheap']:g}", "cand": cand,
                         **_score(nav, split, rf), "mix": mix})
        results[base_id] = {"windows": len(windows), "coverage": float(np.mean([v is not None for v in readings["ratio"]])),
                            "rows": rows}
        print(f"  {base_id}: {len(windows)} windows", flush=True)
    con.close()
    return {"split": str(split.date()), "start": str(sessions[0].date()), "end": str(sessions[-1].date()), "bases": results}


def choose(results: dict) -> dict:
    """The candidate with the best average in-sample Sharpe rank across bases."""
    ranks = []
    for res in results["bases"].values():
        cands = [r for r in res["rows"] if "cand" in r]
        sharpe = pd.Series({r["rule"]: r["in"]["sharpe"] or -9 for r in cands})
        ranks.append(sharpe.rank(ascending=False))
    best = pd.concat(ranks, axis=1).mean(axis=1).sort_values().index[0]
    return next(r["cand"] for r in next(iter(results["bases"].values()))["rows"] if r["rule"] == best) | {"rule": best}


def render(results: dict, chosen: dict) -> str:
    f = lambda v: "—" if v is None else f"{v:.0%}"                                        # noqa: E731
    s = lambda v: "—" if v is None else f"{v:.2f}"                                         # noqa: E731
    lines = [f"Options history {results['start']} → {results['end']}; in-sample before {results['split']}. "
             "Rich → the base's Defensive method, cheap → Aggressive, otherwise → Balanced.\n",
             f"**Chosen rule (best average in-sample Sharpe rank across bases): `{chosen['rule']}`.**\n"]
    for base_id, res in results["bases"].items():
        lines += [f"## `{base_id}` ({res['windows']} windows, IV reading for {res['coverage']:.0%})\n",
                  "| Rule | CAGR in | Sharpe in | CAGR out | Sharpe out | Worst (all) | Mix (D/B/A) |", "|---|---|---|---|---|---|---|"]
        for r in res["rows"]:
            mix = r["mix"] or {}
            mix_s = "/".join(f"{mix.get(t, 0):.0%}" for t in ("Defensive", "Balanced", "Aggressive")) if r["mix"] else ""
            bold = "**" if r["rule"] == chosen["rule"] or r["rule"].startswith("fixed") else ""
            lines.append(f"| {bold}{r['rule']}{bold} | {f(r['in']['cagr'])} | {s(r['in']['sharpe'])} | {f(r['out']['cagr'])} | "
                         f"{s(r['out']['sharpe'])} | {f(r['all']['max_drawdown'])} | {mix_s} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    results = run()
    chosen = choose(results)
    print(write_report(5, "adaptive-options", "Adaptive option tier", render(results, chosen),
                       {"chosen": chosen, **results}))
    print("chosen:", chosen)
    for base_id, res in results["bases"].items():
        for r in res["rows"]:
            if r["rule"].startswith("fixed") or r["rule"] == chosen["rule"]:
                print(f"{base_id:30} {r['rule']:28} in {r['in']['sharpe'] or 0:.2f} / {r['in']['cagr'] or 0:.0%}  "
                      f"out {r['out']['sharpe'] or 0:.2f} / {r['out']['cagr'] or 0:.0%}")


if __name__ == "__main__":
    main()
