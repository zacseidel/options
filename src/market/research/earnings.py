"""Post-earnings drift: does the market's reaction to an announcement keep going?

Events: 8-K 2.02 earnings releases by S&P 500 / 400 members (point-in-time), 2021 → now, with the
reaction features in `market.data.earnings_signals`, known after the close of day +1. Forward returns
vs SPY start at the next close. Quintiles are formed within each calendar quarter (one earnings
season), and seasons are averaged. In-sample: before CUT.

Pre-set rule: a feature survives if the top-minus-bottom quintile spread at 42 sessions has |t| ≥ 2
in-sample and the out-of-sample spread has the same sign and at least half the size. Seasons are few
(~16 in-sample), so t is coarse.

Usage:  python -m market.research.earnings
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.data.earnings_signals import events
from market.data.fundamental_metrics import Fundamentals
from market.research.common import decile_returns, forward_excess, spread, spy_id, summarize, write_report
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
BUCKETS = 5
HORIZONS = (5, 21, 42, 63)
MAIN = 42
FEATURES = {
    "ear": "Earnings-announcement return, day −1 → +1, vs SPY",
    "gap": "Opening gap on the reaction day",
    "held": "Day +1 close vs day 0 open (gap held)",
    "vol_ratio": "Reaction-day volume ÷ prior 20-day mean",
    "pre_21": "Run-up over the 21 sessions before",
    "sue": "Standardized unexpected EPS (if the 10-Q was public by day +1)",
    "rev_sue": "Standardized unexpected revenue (same)",
}


def observations(con, panel) -> pd.DataFrame:
    fund = Fundamentals(con, panel)
    spy = spy_id(con)
    ev = events(con, panel, fund, spy)
    members = con.execute("SELECT universe, security_id, valid_from, valid_to FROM universe_membership "
                          "WHERE universe IN ('sp500', 'sp400') AND security_id IS NOT NULL").df()
    members["valid_from"] = pd.to_datetime(members["valid_from"]).fillna(pd.Timestamp.min)
    members["valid_to"] = pd.to_datetime(members["valid_to"]).fillna(pd.Timestamp.max)
    j = ev.merge(members, on="security_id")
    j = j[(j["valid_from"] <= j["date"]) & (j["valid_to"] > j["date"])].drop_duplicates("accn")
    j = forward_excess(panel, j, spy, HORIZONS)
    j["season"] = pd.to_datetime(j["date"]).dt.to_period("Q").dt.start_time
    return j


def by_season(obs: pd.DataFrame, feature: str, ret: str) -> pd.DataFrame:
    return decile_returns(obs.assign(date=obs["season"]), feature, ret, BUCKETS)


def combo(obs: pd.DataFrame, cut: pd.Timestamp) -> list[str]:
    """The concrete event rules a category would use, in-sample vs out-of-sample (mean per event)."""
    rules = {
        "all events": obs.index == obs.index,
        "EAR ≥ +5%": obs["ear"] >= 0.05,
        "EAR ≥ +5%, gap held, volume ≥ 2×": (obs["ear"] >= 0.05) & (obs["held"] >= 0) & (obs["vol_ratio"] >= 2),
        "EAR ≥ +10%": obs["ear"] >= 0.10,
        "EAR ≥ +5% and SUE ≥ 1": (obs["ear"] >= 0.05) & (obs["sue"] >= 1),
        "EAR ≤ −5%": obs["ear"] <= -0.05,
        "EAR ≤ −5%, gap held, volume ≥ 2×": (obs["ear"] <= -0.05) & (obs["held"] <= 0) & (obs["vol_ratio"] >= 2),
        "EAR ≤ −10%": obs["ear"] <= -0.10,
    }
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                   # noqa: E731
    lines = ["| Rule | Events in | 21d in | 42d in | 63d in | Events out | 21d out | 42d out | 63d out |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, mask in rules.items():
        part = obs[mask]
        ins, outs = part[part["date"] < cut], part[part["date"] >= cut]
        cell = lambda f, h: fmt(summarize(f[f"xs_{h}"])["mean"])                         # noqa: E731
        lines.append(f"| {name} | {len(ins)} | {cell(ins, 21)} | {cell(ins, 42)} | {cell(ins, 63)} | {len(outs)} | "
                     f"{cell(outs, 21)} | {cell(outs, 42)} | {cell(outs, 63)} |")
    return lines


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    obs = observations(con, panel)
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                   # noqa: E731
    tfmt = lambda v: "—" if v is None else f"{v:.1f}"                                    # noqa: E731
    results, lines = {}, []
    lines.append(f"{len(obs):,} announcements by S&P 500 / 400 members, {obs['date'].min().date()} → "
                 f"{obs['date'].max().date()}; {obs['sue'].notna().mean():.0%} had their 10-Q / 10-K public by day +1 "
                 f"(SUE coverage). In-sample before {CUT}. Returns start at the close of day +1.\n")
    lines += ["## Quintile spreads (top − bottom, within each earnings season)\n",
              "| Feature | What | 21d in | 21d out | 42d in | t | 42d out | t | 63d in | 63d out | Survives |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for feature, what in FEATURES.items():
        r = {}
        for h in HORIZONS:
            bs = by_season(obs, feature, f"xs_{h}")
            r[h] = {"in": spread(bs[bs.index < cut]), "out": spread(bs[bs.index >= cut]),
                    "q_in": bs[bs.index < cut].mean().to_dict(), "q_out": bs[bs.index >= cut].mean().to_dict()}
        i, o = r[MAIN]["in"], r[MAIN]["out"]
        r["survives"] = bool(i["t"] is not None and abs(i["t"]) >= 2 and o["mean"] is not None
                             and np.sign(o["mean"]) == np.sign(i["mean"]) and abs(o["mean"]) >= abs(i["mean"]) / 2)
        r["direction"] = "high" if (i["mean"] or 0) > 0 else "low"
        results[feature] = r
        lines.append(f"| `{feature}` | {what} | {fmt(r[21]['in']['mean'])} | {fmt(r[21]['out']['mean'])} | "
                     f"{fmt(i['mean'])} | {tfmt(i['t'])} | {fmt(o['mean'])} | {tfmt(o['t'])} | "
                     f"{fmt(r[63]['in']['mean'])} | {fmt(r[63]['out']['mean'])} | "
                     f"{'**yes** (' + r['direction'] + ')' if r['survives'] else 'no'} |")
    lines += ["", f"## Quintiles ({MAIN} sessions, in / out)\n",
              "| Feature | " + " | ".join(f"Q{q}" for q in range(1, BUCKETS + 1)) + " |", "|---|" + "---|" * BUCKETS]
    for feature, r in results.items():
        lines.append(f"| `{feature}` | " + " | ".join(
            f"{fmt(r[MAIN]['q_in'].get(q))} / {fmt(r[MAIN]['q_out'].get(q))}" for q in range(1, BUCKETS + 1)) + " |")
    lines += ["", "## Concrete event rules (mean excess return per event)\n", *combo(obs, cut)]
    payload = {f: {"survives": r["survives"], "direction": r["direction"],
                   **{str(h): {"in": r[h]["in"], "out": r[h]["out"]} for h in HORIZONS}} for f, r in results.items()}
    print(write_report(3, "earnings", "Post-earnings drift", "\n".join(lines) + "\n", payload))
    for f, r in results.items():
        i, o = r[MAIN]["in"], r[MAIN]["out"]
        print(f"{f:10} in {i['mean'] or 0:+.2%} t={i['t'] or 0:5.1f} | out {o['mean'] or 0:+.2%} t={o['t'] or 0:5.1f} "
              f"| {'SURVIVES ' + r['direction'] if r['survives'] else ''}")
    print("\n".join(combo(obs, cut)))


if __name__ == "__main__":
    main()
