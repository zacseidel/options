"""Insider buying → forward returns, and whether fundamentals separate quality from turnaround buys.

Events: insider purchase days at S&P 500 / 400 members (point-in-time), from
`market.data.insider_signals`, dated the session on/after the Form 4 filing date; returns start at
the next close. Each event's return is measured against SPY and against the **average S&P 500 / 400
stock over the same window** (`vs universe`), because an equal-weight list of mid caps lags SPY on
its own in this period.

Rules are fixed in advance and compared in-sample (before CUT) and out-of-sample. The fundamentals
split uses S&P 500 / 400 Fundamental Momentum as filed by the event date (`fmom`, 0–1):
quality = fmom ≥ 0.5, turnaround = fmom < 0.5.

Usage:  python -m market.research.insiders
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.categories.fundamentals import fmom_score
from market.data.fundamental_metrics import Fundamentals
from market.data.insider_signals import events, universe_mean_excess
from market.research.common import forward_excess, spy_id, summarize, write_report
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HORIZONS = (21, 63, 126)


def observations(con, panel) -> pd.DataFrame:
    ev = events(con, panel)
    members = con.execute("SELECT universe, security_id, valid_from, valid_to FROM universe_membership "
                          "WHERE universe IN ('sp500', 'sp400') AND security_id IS NOT NULL").df()
    members["valid_from"] = pd.to_datetime(members["valid_from"]).fillna(pd.Timestamp.min)
    members["valid_to"] = pd.to_datetime(members["valid_to"]).fillna(pd.Timestamp.max)
    j = ev.merge(members, on="security_id")
    j = j[(j["valid_from"] <= j["date"]) & (j["valid_to"] > j["date"])]
    j = j.drop_duplicates(["security_id", "date"]).drop(columns=["valid_from", "valid_to"])
    spy = spy_id(con)
    j = forward_excess(panel, j, spy, HORIZONS)
    base = universe_mean_excess(panel, members, sorted(j["date"].unique()), spy, HORIZONS)
    for h in HORIZONS:
        j[f"adj_{h}"] = j[f"xs_{h}"] - j["date"].map(base[h])
    # Fundamentals as filed by the event date, ranked within the event's universe that day.
    fund = Fundamentals(con, panel)
    scores = {}
    for d, g in j.groupby("date"):
        for universe in g["universe"].unique():
            ids = members[(members["universe"] == universe) & (members["valid_from"] <= d)
                          & (members["valid_to"] > d)]["security_id"].unique().tolist()
            state = fund.on(d, ids)
            if not state.empty:
                pct = fmom_score(state)
                for sid in g.loc[g["universe"] == universe, "security_id"]:
                    scores[(sid, d)] = pct.get(sid, np.nan)
    j["fmom"] = [scores.get((s, d), np.nan) for s, d in zip(j["security_id"], j["date"])]
    i = panel.sessions.get_indexer(j["date"])
    tr = panel.tr
    cols = tr.columns.get_indexer(j["security_id"])
    past = np.clip(i - 126, 0, None)
    j["ret_6m_before"] = tr.to_numpy()[i, cols] / tr.to_numpy()[past, cols] - 1
    return j


RULES = {
    "every insider purchase day": lambda o: pd.Series(True, index=o.index),
    "first buy in 30 days": lambda o: o["first_buy"],
    "first buy, ≥ $100k": lambda o: o["first_buy"] & (o["value_today"] >= 100_000),
    "C-suite buy ≥ $250k": lambda o: o["csuite"] & (o["value_today"] >= 250_000),
    "cluster forms (≥ 2 insiders in 30 days)": lambda o: o["cluster_start"],
    "cluster reaches 3 insiders": lambda o: o["cluster3_start"],
    "cluster, quality (fmom ≥ 0.5)": lambda o: o["cluster_start"] & (o["fmom"] >= 0.5),
    "cluster, turnaround (fmom < 0.5)": lambda o: o["cluster_start"] & (o["fmom"] < 0.5),
    "first buy ≥ $100k, quality": lambda o: o["first_buy"] & (o["value_today"] >= 100_000) & (o["fmom"] >= 0.5),
    "first buy ≥ $100k, turnaround": lambda o: o["first_buy"] & (o["value_today"] >= 100_000) & (o["fmom"] < 0.5),
    "first buy after a 20%+ fall (6 months)": lambda o: o["first_buy"] & (o["ret_6m_before"] <= -0.20),
    "first buy, not a 10b5-1 plan": lambda o: o["first_buy"] & ~o["planned"].astype(bool),
    "big stake increase (≥ 25% of holding)": lambda o: o["first_buy"] & (o["pct_increase"] >= 0.25),
}


def rule_table(obs: pd.DataFrame, cut: pd.Timestamp) -> tuple[list[str], dict]:
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731
    lines = ["| Rule | Events in | 21d | 63d | 126d | hit 63d | Events out | 21d | 63d | 126d | hit 63d |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    payload = {}
    for name, rule in RULES.items():
        part = obs[pd.Series(rule(obs), index=obs.index).fillna(False).astype(bool)]
        ins, outs = part[part["date"] < cut], part[part["date"] >= cut]
        cells, entry = [], {}
        for label, f in (("in", ins), ("out", outs)):
            stats = {h: summarize(f[f"adj_{h}"]) for h in HORIZONS}
            entry[label] = {str(h): s for h, s in stats.items()}
            hit = stats[63]["hit"]
            cells.append(f"{len(f)} | " + " | ".join(fmt(stats[h]["mean"]) for h in HORIZONS)
                         + f" | {'—' if hit is None else f'{hit:.0%}'}")
        payload[name] = entry
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines, payload


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    obs = observations(con, panel)
    con.close()
    cut = pd.Timestamp(CUT)
    lines = [f"{len(obs):,} insider purchase days at S&P 500 / 400 members, {obs['date'].min().date()} → "
             f"{obs['date'].max().date()} ({obs['security_id'].nunique()} companies); in-sample before {CUT}. "
             f"Fundamental Momentum known for {obs['fmom'].notna().mean():.0%} of events.\n",
             "Returns are excess vs the average S&P 500 / 400 stock over the same window (vs SPY minus the "
             "universe's own excess), so 0% means 'no better than a random member'.\n",
             "## Rules (mean excess vs the universe per event)\n"]
    table, payload = rule_table(obs, cut)
    lines += table
    print(write_report(4, "insiders", "Insider buying → forward returns", "\n".join(lines) + "\n", payload))
    print("\n".join(table))


if __name__ == "__main__":
    main()
