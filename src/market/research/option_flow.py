"""Option-flow exploration: which daily option features predict the next 1 / 4 / 13 weeks?

Observations are S&P 500 / 400 members (point-in-time) on the sessions before each Tuesday / Friday
report, with at least MIN_OPTION_VOLUME contracts a day on average over the prior 20 sessions.
For each feature, names are ranked into deciles **within each date**, and decile returns are
averaged across dates (each date counts once, so busy days don't dominate). Forward returns start
at the next session's close and are measured against SPY (`research.common.forward_excess`).

Pre-set selection rule (decided before looking at the results): a feature survives if the
top-minus-bottom decile spread at 21 sessions has |t| ≥ 2 in-sample (first IN_SAMPLE_MONTHS) and the
out-of-sample spread has the same sign and at least half the in-sample size.

Robustness: pending acquisitions have near-zero realized vol while their options keep some, so they
crowd the top of IV ÷ realized vol. The report repeats the summary for names with realized vol ≥ MIN_RV,
which is the rule the categories use.

Usage:  python -m market.research.option_flow
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from market.data.option_flow import FEATURES, feature_panel
from market.reports.snapshot import report_dates
from market.research.common import forward_excess, markdown_table, spy_id, summarize, write_report
from market.store.db import connect
from market.store.panel import load_panel

IN_SAMPLE_MONTHS = 12
DECILES = 10
MIN_RV = 0.15             # robustness pass: drop deal-pinned names (20-day realized vol below this)
HORIZONS = (5, 21, 63)



def observations(con, panel) -> pd.DataFrame:
    feats = feature_panel(con, panel)
    first, last = feats["date"].min(), feats["date"].max()
    as_of = {panel.session_on_or_before(d - pd.Timedelta(days=1).to_pytimedelta()) for d in
             report_dates(first.date(), last.date())}
    feats = feats[feats["date"].isin(as_of) & feats["liquid"].fillna(False).astype(bool)]
    members = con.execute("SELECT security_id, valid_from, valid_to FROM universe_membership "
                          "WHERE universe IN ('sp500', 'sp400') AND security_id IS NOT NULL").df()
    members["valid_from"] = pd.to_datetime(members["valid_from"]).fillna(pd.Timestamp.min)
    members["valid_to"] = pd.to_datetime(members["valid_to"]).fillna(pd.Timestamp.max)
    joined = feats.merge(members, on="security_id")
    joined = joined[(joined["valid_from"] <= joined["date"]) & (joined["valid_to"] > joined["date"])]
    joined = joined.drop(columns=["valid_from", "valid_to", "liquid"]).drop_duplicates(["date", "security_id"])
    return forward_excess(panel, joined, spy_id(con), HORIZONS)


def decile_returns(obs: pd.DataFrame, feature: str, ret: str) -> pd.DataFrame:
    """date × decile mean of `ret` (deciles formed within each date)."""
    f = obs[["date", feature, ret]].dropna()
    f = f[f.groupby("date")[feature].transform("size") >= DECILES * 3]
    f["decile"] = f.groupby("date")[feature].transform(
        lambda x: pd.qcut(x.rank(method="first"), DECILES, labels=False) + 1)
    return f.groupby(["date", "decile"])[ret].mean().unstack()


def spread(by_date: pd.DataFrame) -> dict:
    s = (by_date[DECILES] - by_date[1]).dropna()
    return summarize(s)


def analyze(obs: pd.DataFrame, cut: pd.Timestamp) -> dict:
    results = {}
    for feature in FEATURES:
        entry = {}
        for h in HORIZONS:
            ret = f"xs_{h}"
            by_date = decile_returns(obs, feature, ret)
            ins, oos = by_date[by_date.index < cut], by_date[by_date.index >= cut]
            entry[h] = {"in": spread(ins), "out": spread(oos),
                        "deciles_in": ins.mean().to_dict(), "deciles_out": oos.mean().to_dict()}
        s_in, s_out = entry[21]["in"], entry[21]["out"]
        survives = bool(s_in["t"] is not None and abs(s_in["t"]) >= 2 and s_out["mean"] is not None
                        and np.sign(s_out["mean"]) == np.sign(s_in["mean"]) and abs(s_out["mean"]) >= abs(s_in["mean"]) / 2)
        entry["survives"] = survives
        entry["direction"] = "high" if (s_in["mean"] or 0) > 0 else "low"
        results[feature] = entry
    return results


def summary_rows(results: dict) -> list[str]:
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731
    tfmt = lambda v: "—" if v is None else f"{v:.1f}"                                      # noqa: E731
    lines = ["| Feature | What | In-sample spread | t | Out-of-sample spread | t | Survives |", "|---|---|---|---|---|---|---|"]
    for feature, r in sorted(results.items(), key=lambda kv: -abs(kv[1][21]["in"]["t"] or 0)):
        i, o = r[21]["in"], r[21]["out"]
        lines.append(f"| `{feature}` | {FEATURES[feature]} | {fmt(i['mean'])} | {tfmt(i['t'])} | {fmt(o['mean'])} | "
                     f"{tfmt(o['t'])} | {'**yes** (' + r['direction'] + ')' if r['survives'] else 'no'} |")
    return lines


def render(results: dict, robust: dict, obs: pd.DataFrame, cut: pd.Timestamp) -> str:
    dates = sorted(obs["date"].unique())
    lines = [f"Observations: {len(obs):,} name-dates on {len(dates)} report dates, "
             f"{pd.Timestamp(dates[0]).date()} → {pd.Timestamp(dates[-1]).date()}; in-sample before {cut.date()}.\n",
             "Spread = top decile minus bottom decile, mean excess return vs SPY per date; t over dates "
             "(overlapping horizons inflate t at 21 / 63 sessions — read the out-of-sample column first).\n",
             "## Summary (21 sessions)\n", *summary_rows(results),
             f"\n## Robustness: realized vol ≥ {MIN_RV:.0%} (drops deal-pinned names)\n", *summary_rows(robust)]
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731
    lines.append("\n## By horizon\n")
    lines.append("| Feature | 5d in | 5d out | 21d in | 21d out | 63d in | 63d out |")
    lines.append("|---|---|---|---|---|---|---|")
    for feature, r in results.items():
        lines.append(f"| `{feature}` | " + " | ".join(f"{fmt(r[h]['in']['mean'])} | {fmt(r[h]['out']['mean'])}" for h in HORIZONS) + " |")
    lines.append("\n## Deciles (21 sessions, mean excess return per date)\n")
    for feature, r in results.items():
        table = pd.DataFrame({"decile": list(range(1, DECILES + 1)),
                              "in-sample": [r[21]["deciles_in"].get(d) for d in range(1, DECILES + 1)],
                              "out-of-sample": [r[21]["deciles_out"].get(d) for d in range(1, DECILES + 1)]})
        lines.append(f"### `{feature}` — {FEATURES[feature]}\n")
        lines.append(markdown_table(table, percent=("in-sample", "out-of-sample")))
    return "\n".join(lines) + "\n"


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    obs = observations(con, panel)
    con.close()
    cut = pd.Timestamp(obs["date"].min()) + pd.DateOffset(months=IN_SAMPLE_MONTHS)
    results = analyze(obs, cut)
    robust = analyze(obs[obs["rv20"] >= MIN_RV], cut)
    payload = {f: {"survives": r["survives"], "direction": r["direction"], "survives_robust": robust[f]["survives"],
                   **{str(h): {"in": r[h]["in"], "out": r[h]["out"]} for h in HORIZONS}} for f, r in results.items()}
    print(write_report(1, "option-flow", "Option flow → forward returns", render(results, robust, obs, cut), payload))
    for f, r in results.items():
        print(f"{f:20} in {r[21]['in']['mean'] or 0:+.2%} t={r[21]['in']['t'] or 0:5.1f} | "
              f"out {r[21]['out']['mean'] or 0:+.2%} t={r[21]['out']['t'] or 0:5.1f} | {'SURVIVES ' + r['direction'] if r['survives'] else ''}")


if __name__ == "__main__":
    main()
