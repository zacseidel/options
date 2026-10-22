"""Steady Leaders (Lab), from `docs/research/07-steady-leaders.md`.

Among S&P 500 names ranked 6–50 by 12-month return — just outside the Leaders' top 5 — the ones that
have stayed in the top 50 the longest. Research (2022-10 → 2026-10): longevity beat short tenure by ~5%
over the next 63 sessions in both halves (S&P 500 only); smoothness measures (steady up days, straight-line
trend, up weeks, few big jumps) did not help, and nothing worked in the S&P 400.

Longevity = share of the last 26 weekly dates (every 5th session) the name ranked in its index's top 50
by 12-month return, among members on each date. Ties go to the better current rank.

Strategy result from 2023-04: top 5 returned 49% a year (Sharpe 0.96) vs 30% (0.62) for the Leaders'
ranks 6–10 — a better way to pick from outside the top 5, though not better than the top 5 itself.
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED
from market.categories.registry import Context, category, source

POOL = (6, 50)
WEEKS = 26


class Ranks12m:
    """12-month-return rank within an index's members on a session, memoized for the whole build."""

    def __init__(self, con, panel):
        m = con.execute("SELECT universe, security_id, valid_from, valid_to FROM universe_membership "
                        "WHERE security_id IS NOT NULL").df()
        m["valid_from"] = pd.to_datetime(m["valid_from"]).fillna(pd.Timestamp.min)
        m["valid_to"] = pd.to_datetime(m["valid_to"]).fillna(pd.Timestamp.max)
        self.members, self.panel, self._memo = m, panel, {}
        self.ret = panel.close / panel.close.shift(252) - 1

    def rank(self, universe: str, session: pd.Timestamp) -> pd.Series:
        key = (universe, session)
        if key not in self._memo:
            m = self.members[self.members["universe"] == universe]
            ids = m[(m["valid_from"] <= session) & (m["valid_to"] > session)]["security_id"].unique()
            self._memo[key] = self.ret.loc[session].reindex(ids).dropna().rank(ascending=False)
        return self._memo[key]


@source("ranks_12m")
def _load(con, panel) -> Ranks12m:
    return Ranks12m(con, panel)


def _steady(ctx: Context, universe: str) -> pd.DataFrame:
    i = ctx.panel.sessions.get_loc(ctx.as_of)
    past = [ctx.panel.sessions[i - 5 * k] for k in range(WEEKS) if i - 5 * k >= 252]
    if len(past) < 20:
        return pd.DataFrame(columns=["score"])
    source_ = ctx.source("ranks_12m")
    ranks = pd.DataFrame({d: source_.rank(universe, d) for d in past})
    now = ranks[past[0]].dropna()
    pool = now[(now >= POOL[0]) & (now <= POOL[1])]
    longevity = (ranks.reindex(pool.index) <= 50).sum(axis=1) / len(past)
    frame = pd.DataFrame({"longevity": longevity, "rank_12m": pool})
    frame = frame.sort_values(["longevity", "rank_12m"], ascending=[False, True]).head(TOP_STORED)
    close = ctx.panel.close
    frame["return_12m"] = (close.iloc[i] / close.iloc[i - 252] - 1).reindex(frame.index)
    return frame.assign(score=frame["longevity"])


@category("steady_sp500", "S&P 500 Steady Leaders", "Momentum", "sp500",
          "S&P 500 names ranked 6–50 by 12-month return, ordered by how many of the last 26 weeks they have spent in "
          "the top 50 (ties to the better current rank): long-running leaders just outside the top 5.",
          lookback_sessions=380)
def steady_sp500(ctx: Context) -> pd.DataFrame:
    return _steady(ctx, "sp500")
