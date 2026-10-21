"""Convergence categories (Lab, PLAN-signals §11), from `docs/research/10-convergence.md`.

A name is flagged by a signal family on a report date if any of the family's lists has it in its top 10
(event lists: listed within their window) — families and lists as in `market.research.convergence`.
Research (S&P 500 / 400, 2022-12 → 2026-10, vs the average member, next 63 sessions): one family +1.3% /
+0.9% (before / after 2025), two +1.8% / +6.3%, three or more +5.2% / +11.5%; momentum + fundamentals was
the strongest consistent pair (+4.2% / +9.7%).

Strategy test from 2022-11 (top 5, hold while listed): Convergence 39% a year (Sharpe 0.74), Momentum +
Fundamentals 38% (0.68) — about twice SPY's 20% but at a lower Sharpe than SPY (0.97) and well below the
momentum lists they overlap with (S&P 500 Leaders 60%, 0.96). Convergence ranks 6–10 were weak (25%).

These categories read the other categories' stored lists for the same report date, so this module must be
imported last (it registers after every other category, and the build stores each category in turn).
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED
from market.categories.registry import Context, category, source
from market.research.convergence import EVENT_WINDOW_DAYS, FAMILIES, TOP


class FamilyFlags:
    def __init__(self, con, panel):
        cats = [c for cs in FAMILIES.values() for c in cs]
        snaps = con.execute(f"SELECT category_id, report_date, security_id, rank FROM category_snapshots "
                            f"WHERE origin = 'backtest' AND category_id IN ({','.join('?' * len(cats))})", cats).df()
        snaps["report_date"] = pd.to_datetime(snaps["report_date"])
        snaps["family"] = snaps["category_id"].map({c: f for f, cs in FAMILIES.items() for c in cs})
        self.ranked = snaps[~snaps["category_id"].isin(EVENT_WINDOW_DAYS) & (snaps["rank"] <= TOP)]
        self.events = snaps[snaps["category_id"].isin(EVENT_WINDOW_DAYS)]

    def on(self, report_date) -> pd.DataFrame:
        """security_id → families (count, names), lists (count) flagging it on `report_date`."""
        d = pd.Timestamp(report_date)
        part = self.ranked[self.ranked["report_date"] == d]
        for cat, days in EVENT_WINDOW_DAYS.items():
            e = self.events[(self.events["category_id"] == cat) & (self.events["report_date"] <= d)
                            & (self.events["report_date"] > d - pd.Timedelta(days=days))]
            part = pd.concat([part, e])
        if part.empty:
            return pd.DataFrame(columns=["families", "family_names", "lists"])
        g = part.groupby("security_id")
        return pd.DataFrame({"families": g["family"].nunique(),
                             "family_names": g["family"].apply(lambda s: ", ".join(sorted(set(s)))),
                             "lists": g["category_id"].nunique()})


@source("family_flags")
def _load(con, panel) -> FamilyFlags:
    return FamilyFlags(con, panel)


def _members(ctx: Context, frame: pd.DataFrame) -> pd.DataFrame:
    ids = set(ctx.members("sp500")) | set(ctx.members("sp400"))
    return frame[frame.index.isin(ids)]


@category("converge_sp900", "Convergence", "Convergence", "sp900",
          "S&P 500 / 400 names flagged by the most independent signal families today (momentum, fundamentals, "
          "reversion, events, options, smart money); at least two. Ties go to the name on more lists.",
          lookback_sessions=0, stage="lab")
def converge_sp900(ctx: Context) -> pd.DataFrame:
    f = _members(ctx, ctx.source("family_flags").on(ctx.report_date))
    f = f[f["families"] >= 2].sort_values(["families", "lists"], ascending=False).head(TOP_STORED)
    return f.assign(score=f["families"] + f["lists"] / 100)


@category("momfund_sp900", "Momentum + Fundamentals", "Convergence", "sp900",
          "S&P 500 / 400 names on both a momentum list and a fundamentals list today, ordered by how many "
          "lists carry them.", lookback_sessions=0, stage="lab")
def momfund_sp900(ctx: Context) -> pd.DataFrame:
    f = _members(ctx, ctx.source("family_flags").on(ctx.report_date))
    both = f["family_names"].str.contains("momentum") & f["family_names"].str.contains("fundamentals")
    f = f[both].sort_values(["lists", "families"], ascending=False).head(TOP_STORED)
    return f.assign(score=f["lists"] + f["families"] / 100)
