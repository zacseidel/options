"""Short interest → forward returns (PLAN-signals §9).

Short interest is reported twice a month by settlement date and published about 8 business days
later, so a reading is used only from its `available` date (`market.data.short_interest`).

Observations: S&P 500 / 400 members (point-in-time) on the first report date of each month, with the
latest published reading. Measures:

  short_pct   short interest ÷ diluted shares (fundamentals as filed by then)
  dtc         days to cover (short interest ÷ average daily volume)
  si_change   change in short interest vs the reading ~1 month earlier
  dtc_change  change in days to cover vs ~1 month earlier

Quintiles within each date and index; returns vs the average member; in-sample before CUT. Also: the
same measures within the top 50 by 12-month return (does short interest change how leaders do?).

Usage:  python -m market.research.short_interest
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.data.fundamental_metrics import Fundamentals
from market.research.common import (decile_returns, forward_excess, members_frame, spread, spy_id,
                                    universe_mean_excess, write_report)
from market.research.fundamentals import monthly_dates
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HORIZONS = (21, 63, 126)
MAIN = 63
FEATURES = {
    "short_pct": "Short interest ÷ diluted shares",
    "dtc": "Days to cover",
    "si_change": "Change in short interest vs ~1 month earlier",
    "dtc_change": "Change in days to cover vs ~1 month earlier",
}


def readings(con) -> pd.DataFrame:
    j = con.execute("SELECT * FROM short_interest ORDER BY security_id, settlement_date").df()
    j["settlement_date"] = pd.to_datetime(j["settlement_date"])
    j["available"] = pd.to_datetime(j["available"])
    g = j.groupby("security_id")
    j["si_change"] = j["short_interest"] / g["short_interest"].shift(2) - 1       # two readings ≈ one month
    j["dtc_change"] = j["days_to_cover"] - g["days_to_cover"].shift(2)
    return j


def observations(con, panel, si: pd.DataFrame) -> pd.DataFrame:
    members = members_frame(con)
    fund = Fundamentals(con, panel)
    rows = []
    close = panel.close
    for d in monthly_dates(panel):
        known = si[si["available"] <= d].drop_duplicates("security_id", keep="last").set_index("security_id")
        known = known[(d - known["settlement_date"]).dt.days <= 45]
        for universe in ("sp500", "sp400"):
            m = members[(members["universe"] == universe) & (members["valid_from"] <= d) & (members["valid_to"] > d)]
            ids = [s for s in m["security_id"].unique() if s in known.index]
            if not ids:
                continue
            f = known.loc[ids, ["short_interest", "days_to_cover", "si_change", "dtc_change"]].rename(
                columns={"days_to_cover": "dtc"})
            state = fund.on(d, ids)
            f["short_pct"] = f["short_interest"] / state["diluted_shares"].reindex(f.index)
            i = panel.sessions.get_loc(d)
            if i >= 252:
                ret = (close.iloc[i] / close.iloc[i - 252] - 1).reindex(m["security_id"].unique()).dropna()
                f["mom_rank"] = ret.rank(ascending=False).reindex(f.index)
            rows.append(f.assign(date=d, universe=universe).reset_index(names="security_id"))
    obs = pd.concat(rows, ignore_index=True)
    obs.loc[(obs["short_pct"] <= 0) | (obs["short_pct"] > 1), "short_pct"] = np.nan
    spy = spy_id(con)
    obs = forward_excess(panel, obs, spy, HORIZONS)
    base = universe_mean_excess(panel, members, sorted(obs["date"].unique()), spy, HORIZONS)
    for h in HORIZONS:
        obs[f"adj_{h}"] = obs[f"xs_{h}"] - obs["date"].map(base[h])
    return obs


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    si = readings(con)
    obs = observations(con, panel, si)
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:+.2%}"     # noqa: E731
    tfmt = lambda v: "—" if v is None else f"{v:.1f}"                                               # noqa: E731
    lines = [f"{len(obs):,} name-months, {obs['date'].nunique()} monthly dates {obs['date'].min().date()} → "
             f"{obs['date'].max().date()}; readings used from settlement + 8 business days; "
             f"in-sample before {CUT}. Returns vs the average member of the same index.\n"]
    payload = {}
    for universe in ("sp500", "sp400"):
        for pool_name, pool in (("all members", lambda o: o.index == o.index),
                                ("top 50 by 12-month return", lambda o: o["mom_rank"] <= 50)):
            part = obs[(obs["universe"] == universe) & pool(obs)]
            lines += [f"## {universe.upper()} — {pool_name}\n",
                      "| Measure (top − bottom quintile) | 63d in | t | 63d out | t | 126d in | 126d out | Q1 / Q5 63d in | Q1 / Q5 63d out |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for f, what in FEATURES.items():
                res = {}
                for h in (63, 126):
                    bd = decile_returns(part, f, f"adj_{h}", 5)
                    res[h] = (bd[bd.index < cut], bd[bd.index >= cut])
                i63, o63 = spread(res[63][0]), spread(res[63][1])
                q = lambda b, k: b[k].mean() if k in b else None                                     # noqa: E731
                payload[f"{universe}/{pool_name}/{f}"] = {"in": i63, "out": o63}
                lines.append(f"| `{f}` {what} | {fmt(i63['mean'])} | {tfmt(i63['t'])} | {fmt(o63['mean'])} | {tfmt(o63['t'])} | "
                             f"{fmt(spread(res[126][0])['mean'])} | {fmt(spread(res[126][1])['mean'])} | "
                             f"{fmt(q(res[63][0], 1))} / {fmt(q(res[63][0], 5))} | {fmt(q(res[63][1], 1))} / {fmt(q(res[63][1], 5))} |")
            lines.append("")
    outcome = ("> **Outcome (2026-10-21).** Days to cover is the signal. Kept: S&P 500 Leaders skipping the top fifth\n"
               "> of days to cover (68% a year, Sharpe 1.07 vs 60% / 0.96 unfiltered, from 2022-11). The same filter\n"
               "> made S&P 400 Leaders and S&P 500 Rank Momentum worse, so those were dropped.\n\n")
    print(write_report(8, "short-interest", "Short interest → forward returns", outcome + "\n".join(lines) + "\n", payload))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
