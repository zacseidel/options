"""Steady leaders: among the top-50 momentum names (excluding the top 5), do the most *consistent* ones
— long-standing members of the top 50, or names that rose steadily rather than in a few jumps — do better?

The idea builds on "frog in the pan" (Da, Gurun & Warachka 2014): momentum built from many small moves
persists more than momentum from a few big jumps, because investors under-react to gradual news.

Pool on each date, per index: ranks 6–50 by 12-month return (point-in-time members). Measures (all from
prices up to the date):

  longevity   share of the last 26 weekly dates the name was in the top 50
  smooth_126  (up days − down days) / days over the last 126 sessions; smooth_252 over 252
  trend_r2    R² of log price on time over the last 126 sessions (straight-line climb)
  up_weeks    share of up weeks over the last 26
  jumpiness   best 21-session log return ÷ 12-month log return (lower = gains spread out)

Monthly observations; quintiles within each date and index; forward returns vs the average member.
In-sample before CUT. Also shown: the top-5 leaders themselves and the whole pool, for reference.

Usage:  python -m market.research.steady_leaders
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.research.common import (decile_returns, forward_excess, members_frame, spread, spy_id, summarize,
                                    universe_mean_excess, write_report)
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HORIZONS = (21, 63, 126)
MAIN = 63
POOL = (6, 50)
FEATURES = {
    "longevity": "Share of the last 26 weeks in the top 50",
    "smooth_126": "Up days − down days, last 126 sessions",
    "smooth_252": "Up days − down days, last 252 sessions",
    "trend_r2": "R² of a straight-line fit to log price, last 126 sessions",
    "up_weeks": "Share of up weeks, last 26",
    "jumpiness": "Best 21-session gain ÷ 12-month gain (lower = steadier)",
}


def weekly_ranks(panel, members: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Rank by 12-month return within each index, on every Friday-ish session (the week's last)."""
    close = panel.close
    ret12 = close / close.shift(252) - 1
    weeks = pd.Series(panel.sessions, index=panel.sessions).groupby(panel.sessions.to_period("W")).last()
    weeks = weeks[weeks >= panel.sessions[252]]
    ranks = {}
    for universe in ("sp500", "sp400"):
        m = members[members["universe"] == universe]
        rows = {}
        for d in weeks:
            live = m[(m["valid_from"] <= d) & (m["valid_to"] > d)]["security_id"].unique()
            r = ret12.loc[d].reindex(live).dropna()
            rows[d] = r.rank(ascending=False)
        ranks[universe] = pd.DataFrame(rows).T
    return ret12, {"weeks": list(weeks), **ranks}


def measures(panel, d: pd.Timestamp, ids: list[str]) -> pd.DataFrame:
    i = panel.sessions.get_loc(d)
    close = panel.close.iloc[max(0, i - 252): i + 1].reindex(columns=ids)
    logp = np.log(close)
    daily = logp.diff().iloc[1:]
    last126 = daily.iloc[-126:]
    smooth = lambda x: ((x > 0).sum() - (x < 0).sum()) / x.notna().sum()                  # noqa: E731
    y = logp.iloc[-127:].ffill().to_numpy()
    t = np.arange(len(y), dtype=float)
    t = (t - t.mean())[:, None]
    yc = y - np.nanmean(y, axis=0)
    beta = np.nansum(t * yc, axis=0) / (t ** 2).sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = pd.Series(1 - np.nansum((yc - t * beta) ** 2, axis=0) / np.nansum(yc ** 2, axis=0), index=ids)
    beta = pd.Series(beta, index=ids)
    weekly = close.iloc[::-5].iloc[::-1].pct_change().iloc[-26:]
    total = logp.iloc[-1] - logp.iloc[0]
    best21 = (logp - logp.shift(21)).max()
    return pd.DataFrame({
        "smooth_126": smooth(last126), "smooth_252": smooth(daily), "trend_r2": r2.where(beta > 0),
        "up_weeks": (weekly > 0).sum() / weekly.notna().sum(),
        "jumpiness": (best21 / total).where(total > 0),
    })


def observations(con, panel) -> pd.DataFrame:
    members = members_frame(con)
    ret12, ranks = weekly_ranks(panel, members)
    weeks = ranks["weeks"]
    monthly = pd.Series(weeks, index=weeks).groupby(pd.DatetimeIndex(weeks).to_period("M")).first()
    rows = []
    for universe in ("sp500", "sp400"):
        r = ranks[universe]
        top50 = (r <= 50).astype(float).where(r.notna())
        longevity = top50.rolling(26, min_periods=20).mean()
        for d in monthly:
            if d not in r.index or d not in longevity.index:
                continue
            now = r.loc[d].dropna()
            pool = now[(now >= POOL[0]) & (now <= POOL[1])].index.tolist()
            top5 = now[now <= 5].index.tolist()
            m = measures(panel, d, pool + top5)
            frame = m.assign(longevity=longevity.loc[d].reindex(m.index), rank_12m=now.reindex(m.index),
                             group=["pool" if s in pool else "top5" for s in m.index],
                             universe=universe, date=d)
            rows.append(frame.reset_index(names="security_id"))
    obs = pd.concat(rows, ignore_index=True)
    spy = spy_id(con)
    obs = forward_excess(panel, obs, spy, HORIZONS)
    base = universe_mean_excess(panel, members, sorted(obs["date"].unique()), spy, HORIZONS)
    for h in HORIZONS:
        obs[f"adj_{h}"] = obs[f"xs_{h}"] - obs["date"].map(base[h])
    obs["jumpiness_inv"] = -obs["jumpiness"]
    obs["composite"] = obs.groupby(["date", "universe"])[["longevity", "smooth_126", "trend_r2"]].rank(pct=True).mean(axis=1)
    return obs


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    obs = observations(con, panel)
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731
    tfmt = lambda v: "—" if v is None else f"{v:.1f}"                                      # noqa: E731
    feats = {**FEATURES, "jumpiness_inv": "−jumpiness (higher = steadier)",
             "composite": "Mean percentile of longevity, smooth_126 and trend_r2"}
    lines = [f"{obs['date'].nunique()} monthly dates, {obs['date'].min().date()} → {obs['date'].max().date()}; "
             f"in-sample before {CUT}. Returns vs the average member of the same index.\n"]
    payload = {}
    for universe in ("sp500", "sp400"):
        part = obs[obs["universe"] == universe]
        pool = part[part["group"] == "pool"]
        lines += [f"## {universe.upper()} — pool = ranks {POOL[0]}–{POOL[1]} by 12-month return\n",
                  "| Group | n in | 63d in | 126d in | n out | 63d out | 126d out |", "|---|---|---|---|---|---|---|"]
        for label, g in (("top 5 (the Leaders)", part[part["group"] == "top5"]), ("whole pool (6–50)", pool)):
            ins, outs = g[g["date"] < cut], g[g["date"] >= cut]
            lines.append(f"| {label} | {len(ins)} | {fmt(summarize(ins['adj_63'])['mean'])} | {fmt(summarize(ins['adj_126'])['mean'])} | "
                         f"{len(outs)} | {fmt(summarize(outs['adj_63'])['mean'])} | {fmt(summarize(outs['adj_126'])['mean'])} |")
        lines += ["", "| Measure (top − bottom quintile of the pool) | 63d in | t | 63d out | t | 126d in | 126d out | top quintile 63d in / out |",
                  "|---|---|---|---|---|---|---|---|"]
        payload[universe] = {}
        for f, what in feats.items():
            res = {}
            for h in (63, 126):
                bd = decile_returns(pool, f, f"adj_{h}", 5)
                res[h] = (spread(bd[bd.index < cut]), spread(bd[bd.index >= cut]),
                          bd[bd.index < cut][5].mean() if 5 in bd else None, bd[bd.index >= cut][5].mean() if 5 in bd else None)
            i63, o63, top_in, top_out = res[63]
            payload[universe][f] = {"63": {"in": i63, "out": o63}, "126": {"in": res[126][0], "out": res[126][1]}}
            lines.append(f"| `{f}` {what} | {fmt(i63['mean'])} | {tfmt(i63['t'])} | {fmt(o63['mean'])} | {tfmt(o63['t'])} | "
                         f"{fmt(res[126][0]['mean'])} | {fmt(res[126][1]['mean'])} | {fmt(top_in)} / {fmt(top_out)} |")
        lines.append("")
    outcome = ("> **Outcome (2026-10-21).** Only longevity (S&P 500) showed an edge; smoothness did not, and nothing\n"
               "> worked in the S&P 400. Built as the Lab category S&P 500 Steady Leaders: from 2023-04, top 5 by\n"
               "> longevity returned 49% a year (Sharpe 0.96) vs 30% (0.62) for S&P 500 Leaders ranks 6–10 and 69%\n"
               "> (1.05) for the Leaders' top 5; its ranks 6–10 were weak (10%) and were not kept.\n\n")
    print(write_report(7, "steady-leaders", "Steady leaders: consistency within the top 50",
                       outcome + "\n".join(lines) + "\n", payload))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
