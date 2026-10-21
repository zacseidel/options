"""Fundamentals exploration: which point-in-time company metrics predict the next 1 / 3 / 6 months?

Observations: S&P 500 and S&P 400 members (point-in-time) on the first report date of each month,
with each company's fundamentals as filed by then (`Fundamentals`, usable from the day after the
filing). Names are ranked into quintiles within each date and universe; returns vs SPY start at the
next session's close. In-sample: before CUT; out-of-sample: CUT onward.

Pre-set selection rule (before looking): a feature survives in a universe if the top-minus-bottom
quintile spread at 63 sessions has |t| ≥ 2 in-sample and the out-of-sample spread has the same sign
and at least half the in-sample size. Monthly dates with 63-session horizons overlap, so t is
inflated ~1.7×; read it as a ranking, not a p-value.

Also reports, for the user's "find winners earlier" question, how each feature's top quintile does
among names that are NOT already 12-month momentum leaders (outside the universe's top 50).

Usage:  python -m market.research.fundamentals
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.data.fundamental_metrics import Fundamentals
from market.reports.snapshot import report_dates
from market.research.common import decile_returns, forward_excess, spread, spy_id, summarize, write_report
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
START = date(2022, 1, 1)
BUCKETS = 5
HORIZONS = (21, 63, 126)
MAIN = 63

FEATURES = {
    "rev_yoy_q": "Revenue growth, latest quarter vs a year earlier",
    "rev_accel": "Revenue growth acceleration (this quarter's YoY − last quarter's)",
    "rev_ttm_yoy": "Trailing-12-month revenue growth",
    "eps_yoy_q": "EPS growth, latest quarter YoY (positive base)",
    "eps_accel": "EPS growth acceleration",
    "ni_ttm_yoy": "Trailing net income growth (positive base)",
    "gross_margin_chg": "Gross margin change vs a year earlier (TTM)",
    "op_margin_chg": "Operating margin change vs a year earlier (TTM)",
    "fcf_margin": "Free-cash-flow margin (TTM)",
    "fcf_yield": "Free-cash-flow yield (TTM FCF ÷ market cap)",
    "shares_yoy": "Diluted share count change YoY (negative = buybacks)",
    "rev_up_12q": "Quarters of the last 12 with revenue up YoY",
    "rev_yoy_std_8q": "Volatility of quarterly revenue growth (last 8)",
    "ps": "Price ÷ sales",
    "pe": "Price ÷ earnings",
    "ps_chg": "Change in price ÷ sales vs a year earlier (multiple expansion)",
    "pe_chg": "Change in P/E vs a year earlier (multiple expansion)",
}


def monthly_dates(panel) -> list[pd.Timestamp]:
    """As-of sessions of the first Tue/Fri report of each month."""
    dates = report_dates(START, panel.sessions[-1].date())
    firsts = pd.Series(dates).groupby([pd.Series(dates).map(lambda d: (d.year, d.month))]).first()
    return [panel.session_on_or_before(d - pd.Timedelta(days=1).to_pytimedelta()) for d in firsts]


def observations(con, panel, fund: Fundamentals) -> pd.DataFrame:
    members = con.execute("SELECT universe, security_id, valid_from, valid_to FROM universe_membership "
                          "WHERE universe IN ('sp500', 'sp400') AND security_id IS NOT NULL").df()
    members["valid_from"] = pd.to_datetime(members["valid_from"]).fillna(pd.Timestamp.min)
    members["valid_to"] = pd.to_datetime(members["valid_to"]).fillna(pd.Timestamp.max)
    frames = []
    for when in monthly_dates(panel):
        live = members[(members["valid_from"] <= when) & (members["valid_to"] > when)]
        ids = sorted(set(live["security_id"]))
        year_ago = panel.session_on_or_before((when - pd.DateOffset(years=1)).date())
        if year_ago is None:                       # price history starts too late for 12-month changes
            continue
        f = fund.with_multiples(when, ids, year_ago)
        if f.empty:
            continue
        f = f.reindex(columns=list(FEATURES)).assign(date=when)
        uni = live.drop_duplicates("security_id").set_index("security_id")["universe"]
        f["universe"] = uni.reindex(f.index)
        px_then = panel.close.loc[year_ago].reindex(f.index)
        f["return_12m"] = panel.close.loc[when].reindex(f.index) / px_then - 1
        f["mom_rank"] = f.groupby("universe")["return_12m"].rank(ascending=False)
        frames.append(f.reset_index(names="security_id"))
    obs = pd.concat(frames, ignore_index=True)
    return forward_excess(panel, obs, spy_id(con), HORIZONS)


def analyze(obs: pd.DataFrame) -> dict:
    cut = pd.Timestamp(CUT)
    out = {}
    for universe in ("sp500", "sp400"):
        part = obs[obs["universe"] == universe]
        not_leaders = part[part["mom_rank"] > 50]
        res = {}
        for feature in FEATURES:
            entry = {}
            for h in HORIZONS:
                by_date = decile_returns(part, feature, f"xs_{h}", BUCKETS)
                entry[h] = {"in": spread(by_date[by_date.index < cut]), "out": spread(by_date[by_date.index >= cut]),
                            "q_in": by_date[by_date.index < cut].mean().to_dict(),
                            "q_out": by_date[by_date.index >= cut].mean().to_dict()}
            nl = decile_returns(not_leaders, feature, f"xs_{MAIN}", BUCKETS)
            entry["not_leaders"] = {"in": spread(nl[nl.index < cut]), "out": spread(nl[nl.index >= cut])}
            i, o = entry[MAIN]["in"], entry[MAIN]["out"]
            entry["survives"] = bool(i["t"] is not None and abs(i["t"]) >= 2 and o["mean"] is not None
                                     and np.sign(o["mean"]) == np.sign(i["mean"]) and abs(o["mean"]) >= abs(i["mean"]) / 2)
            entry["direction"] = "high" if (i["mean"] or 0) > 0 else "low"
            res[feature] = entry
        out[universe] = res
    return out


def render(results: dict, obs: pd.DataFrame) -> str:
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                  # noqa: E731
    tfmt = lambda v: "—" if v is None else f"{v:.1f}"                                   # noqa: E731
    dates = sorted(obs["date"].unique())
    lines = [f"{len(obs):,} name-months on {len(dates)} monthly dates, {pd.Timestamp(dates[0]).date()} → "
             f"{pd.Timestamp(dates[-1]).date()}; in-sample before {CUT}. Quintiles within each date and universe; "
             "spread = top quintile minus bottom, excess return vs SPY.\n"]
    for universe, res in results.items():
        lines += [f"## {universe.upper()} — {MAIN} sessions\n",
                  "| Feature | What | In | t | Out | t | Not-leaders in | Not-leaders out | Survives |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for feature, r in sorted(res.items(), key=lambda kv: -abs(kv[1][MAIN]["in"]["t"] or 0)):
            i, o, n = r[MAIN]["in"], r[MAIN]["out"], r["not_leaders"]
            lines.append(f"| `{feature}` | {FEATURES[feature]} | {fmt(i['mean'])} | {tfmt(i['t'])} | {fmt(o['mean'])} | "
                         f"{tfmt(o['t'])} | {fmt(n['in']['mean'])} | {fmt(n['out']['mean'])} | "
                         f"{'**yes** (' + r['direction'] + ')' if r['survives'] else 'no'} |")
        lines += ["", f"### {universe.upper()} by horizon (spread in / out)\n",
                  "| Feature | " + " | ".join(f"{h}d in | {h}d out" for h in HORIZONS) + " |",
                  "|---|" + "---|" * (2 * len(HORIZONS))]
        for feature, r in res.items():
            lines.append(f"| `{feature}` | " + " | ".join(f"{fmt(r[h]['in']['mean'])} | {fmt(r[h]['out']['mean'])}"
                                                         for h in HORIZONS) + " |")
        lines += ["", f"### {universe.upper()} quintiles ({MAIN} sessions, in / out)\n",
                  "| Feature | " + " | ".join(f"Q{q}" for q in range(1, BUCKETS + 1)) + " |",
                  "|---|" + "---|" * BUCKETS]
        for feature, r in res.items():
            cells = [f"{fmt(r[MAIN]['q_in'].get(q))} / {fmt(r[MAIN]['q_out'].get(q))}" for q in range(1, BUCKETS + 1)]
            lines.append(f"| `{feature}` | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    fund = Fundamentals(con, panel)
    obs = observations(con, panel, fund)
    con.close()
    results = analyze(obs)
    payload = {u: {f: {"survives": r["survives"], "direction": r["direction"],
                       **{str(h): {"in": r[h]["in"], "out": r[h]["out"]} for h in HORIZONS}}
                   for f, r in res.items()} for u, res in results.items()}
    print(write_report(2, "fundamentals", "Fundamentals → forward returns", render(results, obs), payload))
    for universe, res in results.items():
        for f, r in res.items():
            i, o = r[MAIN]["in"], r[MAIN]["out"]
            print(f"{universe} {f:18} in {i['mean'] or 0:+.2%} t={i['t'] or 0:5.1f} | out {o['mean'] or 0:+.2%} "
                  f"t={o['t'] or 0:5.1f} | {'SURVIVES ' + r['direction'] if r['survives'] else ''}")


if __name__ == "__main__":
    main()
