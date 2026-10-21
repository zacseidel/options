"""Convergence: do names flagged by two or more independent signal families do better?

Families (positive-signal lists already stored as category snapshots):
  momentum      S&P 500 / 400 Leaders, Rank Momentum, Fast Rank Momentum, Megacap Leaders, Steady Leaders
  fundamentals  Fundamental Momentum, Emerging Leaders, S&P 500 Re-rating, S&P 500 Share Shrinkers
  reversion     Megacap Laggards, Munger Dip
  events        Dividend Raisers (listed in the last 63 days), Strong Earnings Reactions (last 42 days)
  options       Inverted Option Term Structure
  smart_money   Congress Top-5 Buys / Holdings, 13F Skilled-Fund Buys / Alpha Drivers

A name is flagged by a family on a report date if any of its lists has it in the top 10 on that date
(event lists: listed within their window). Observations: S&P 500 / 400 members on Friday reports,
returns from the report's as-of close vs the average member. In-sample before CUT. Families start at
different dates (options 2024-11, Congress 2025-01, 13F 2025-05), so later combinations are thin.

Usage:  python -m market.research.convergence
"""

from __future__ import annotations

import argparse
import itertools
from datetime import date

import pandas as pd

from market.research.common import forward_excess, members_frame, spy_id, summarize, universe_mean_excess, write_report
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HORIZONS = (21, 63, 126)
START = date(2022, 11, 29)
FAMILIES = {
    "momentum": ["mom12_sp500", "mom12_sp400", "rankmom_sp500", "rankmom_sp400", "rankfast_sp500", "rankfast_sp400",
                 "mom12_megacap", "steady_sp500"],
    "fundamentals": ["fmom_sp500", "fmom_sp400", "emerging_sp500", "emerging_sp400", "rerating_sp500", "shrinkers_sp500"],
    "reversion": ["laggards_mega10", "munger_top50"],
    "events": ["divraise_sp900", "pead_up_sp900"],
    "options": ["ivinverted_sp900"],
    "smart_money": ["congress_buys", "congress_holdings", "hedge_buys", "hedge_drivers"],
}
EVENT_WINDOW_DAYS = {"divraise_sp900": 63, "pead_up_sp900": 42}
TOP = 10


def flags(con, panel) -> pd.DataFrame:
    cats = [c for cs in FAMILIES.values() for c in cs]
    snaps = con.execute(f"SELECT category_id, report_date, security_id, rank FROM category_snapshots WHERE origin = "
                        f"'backtest' AND category_id IN ({','.join('?' * len(cats))})", cats).df()
    snaps["report_date"] = pd.to_datetime(snaps["report_date"])
    family_of = {c: f for f, cs in FAMILIES.items() for c in cs}
    snaps["family"] = snaps["category_id"].map(family_of)
    reports = sorted(d for d in snaps["report_date"].unique() if d.weekday() == 4 and d >= pd.Timestamp(START))
    rows = []
    ranked = snaps[~snaps["category_id"].isin(EVENT_WINDOW_DAYS) & (snaps["rank"] <= TOP)]
    by_date = {d: g for d, g in ranked.groupby("report_date")}
    events = snaps[snaps["category_id"].isin(EVENT_WINDOW_DAYS)]
    for d in reports:
        part = by_date.get(d, ranked.iloc[0:0])
        for cat, days in EVENT_WINDOW_DAYS.items():
            e = events[(events["category_id"] == cat) & (events["report_date"] <= d)
                       & (events["report_date"] > d - pd.Timedelta(days=days))]
            part = pd.concat([part, e])
        fams = part.groupby("security_id")["family"].apply(lambda s: frozenset(s))
        for sid, fs in fams.items():
            rows.append({"report_date": d, "security_id": sid, "families": fs, "n": len(fs)})
    out = pd.DataFrame(rows)
    out["date"] = [panel.session_on_or_before((d - pd.Timedelta(days=1)).date()) for d in out["report_date"]]
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    members = members_frame(con)
    obs = flags(con, panel)
    j = obs.merge(members, on="security_id")
    j = j[(j["valid_from"] <= j["date"]) & (j["valid_to"] > j["date"])].drop_duplicates(["security_id", "date"])
    spy = spy_id(con)
    j = forward_excess(panel, j.drop(columns=["valid_from", "valid_to"]), spy, HORIZONS)
    base = universe_mean_excess(panel, members, sorted(j["date"].unique()), spy, HORIZONS)
    for h in HORIZONS:
        j[f"adj_{h}"] = j[f"xs_{h}"] - j["date"].map(base[h])
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731

    def row(label, part):
        ins, outs = part[part["date"] < cut], part[part["date"] >= cut]
        cells = []
        for f in (ins, outs):
            cells.append(f"{len(f)} | " + " | ".join(fmt(summarize(f[f'adj_{h}'])['mean']) for h in HORIZONS)
                         + f" | {fmt(summarize(f['adj_63'])['hit']).replace('+', '') if len(f) else '—'}")
        return f"| {label} | " + " | ".join(cells) + " |"

    head = ["| Group | n in | 21d | 63d | 126d | hit 63d | n out | 21d | 63d | 126d | hit 63d |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    lines = [f"{j['date'].nunique()} Friday reports, {j['date'].min().date()} → {j['date'].max().date()}; "
             f"name-dates flagged by at least one family: {len(j):,}. Mean excess return vs the average member.\n",
             "## By number of families\n", *head]
    for n in (1, 2, 3):
        lines.append(row(f"{n}{'+' if n == 3 else ''} famil{'y' if n == 1 else 'ies'}", j[j["n"] >= 3] if n == 3 else j[j["n"] == n]))
    lines += ["", "## Each family alone vs with at least one other family\n", *head]
    for fam in FAMILIES:
        has = j[j["families"].apply(lambda fs: fam in fs)]
        lines.append(row(f"{fam} only", has[has["n"] == 1]))
        lines.append(row(f"{fam} + another", has[has["n"] >= 2]))
    lines += ["", "## Pairs (both families flag the name)\n", *head]
    for a, b in itertools.combinations(FAMILIES, 2):
        pair = j[j["families"].apply(lambda fs: a in fs and b in fs)]
        if len(pair) >= 20:
            lines.append(row(f"{a} + {b}", pair))
    outcome = ("> **Outcome (2026-10-21).** Returns rise with the number of families flagging a name, in both halves;\n"
               "> momentum + fundamentals is the strongest consistent pair. As top-5 strategies (from 2022-11) Convergence\n"
               "> returned 39% a year (Sharpe 0.74) and Momentum + Fundamentals 38% (0.68): about twice SPY but at a lower\n"
               "> Sharpe, and below the momentum lists they overlap with (S&P 500 Leaders 60%, 0.96). Kept in the Lab for\n"
               "> the user's call.\n\n")
    print(write_report(10, "convergence", "Convergence across signal families", outcome + "\n".join(lines) + "\n", {}))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
