"""Fundamental categories (Lab, PLAN-signals §5), from `docs/research/02-fundamentals.md`.

Fundamentals are EDGAR XBRL facts as first filed, usable from the day after filing
(`market.data.fundamental_metrics`). Research, 2022-10 → 2026-10 (rules chosen before 2025):

  * **margin expansion** (gross and operating margin vs a year earlier) led the next 3–6 months in
    both the S&P 500 and the S&P 400, in both halves; trailing **earnings growth** did in the S&P 500;
  * revenue / EPS acceleration, multiple expansion and share shrinkage showed nothing reliable;
  * steady growers (revenue up in most of the last 12 quarters) did well until 2025, then lagged.

`fmom_*` (Fundamental Momentum) ranks the survivors; S&P 400 Emerging Leaders, S&P 500 Re-rating and S&P 500
Share Shrinkers test concentrated versions of other ideas. All are Lab.

Tried and dropped 2026-10-21 (user, after the overview): Steady Compounders (S&P 500 −14% / S&P 400 −7% a
year since 2021 — steady past growth picked richly priced names), S&P 400 Re-rating, S&P 400 Share
Shrinkers, and a fundamentals filter on Megacap Laggards and Munger Dip (both made the originals worse).
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED, _leaders
from market.categories.registry import Context, category, source
from market.data.fundamental_metrics import Fundamentals

FMOM_FEATURES = ["gross_margin_chg", "op_margin_chg", "ni_ttm_yoy"]


@source("fundamentals")
def _load(con, panel) -> Fundamentals:
    return Fundamentals(con, panel)


def _state(ctx: Context, universe: str, multiples: bool = False) -> pd.DataFrame:
    fund = ctx.source("fundamentals")
    ids = ctx.members(universe)
    if multiples:
        year_ago = ctx.panel.session_on_or_before((ctx.as_of - pd.DateOffset(years=1)).date())
        return fund.with_multiples(ctx.as_of, ids, year_ago)
    return fund.on(ctx.as_of, ids)


def fmom_score(frame: pd.DataFrame) -> pd.Series:
    """Mean percentile (within the universe that day) of the surviving features; needs ≥ 2 of 3."""
    pct = frame[FMOM_FEATURES].rank(pct=True)
    return pct.mean(axis=1).where(pct.notna().sum(axis=1) >= 2)


def _fmom(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    frame = frame.assign(fmom=fmom_score(frame)).dropna(subset=["fmom"])
    frame = frame[frame["rev_yoy_q"] > 0]                 # margins from growth, not from shrinking
    frame = frame.sort_values("fmom", ascending=False).head(TOP_STORED)
    return frame[["fmom", *FMOM_FEATURES, "rev_yoy_q"]].assign(score=frame["fmom"])


@category("fmom_sp500", "S&P 500 Fundamental Momentum", "Fundamentals", "sp500",
          "S&P 500 members with growing revenue ranked by margin expansion (gross and operating margin vs a "
          "year earlier) and trailing earnings growth, as filed.", lookback_sessions=0)
def fmom_sp500(ctx: Context) -> pd.DataFrame:
    return _fmom(ctx, "sp500")


@category("fmom_sp400", "S&P 400 Fundamental Momentum", "Fundamentals", "sp400",
          "S&P 400 members with growing revenue ranked by margin expansion and trailing earnings growth, as filed.",
          lookback_sessions=0)
def fmom_sp400(ctx: Context) -> pd.DataFrame:
    return _fmom(ctx, "sp400")


def _emerging(ctx: Context, universe: str, outside_top: int | None = 25) -> pd.DataFrame:
    """Top-quintile Fundamental Momentum whose 12-month price rank is improving (and, by default, outside the
    top 25; `outside_top=None` keeps the leaders too)."""
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    frame = frame.assign(fmom=fmom_score(frame))
    leaders = _leaders(ctx, ctx.members(universe), keep=10_000)    # all names with an improving/steady rank
    ranked = ctx.closes(ctx.members(universe), "now", "12m").dropna()
    rank_12m = (ranked["now"] / ranked["12m"] - 1).rank(ascending=False)
    frame = frame.assign(rank_12m=rank_12m.reindex(frame.index),
                         rank_change=leaders["rank_change"].reindex(frame.index))
    frame = frame[(frame["fmom"] >= 0.8) & (frame["rank_change"] > 0)]
    if outside_top is not None:
        frame = frame[frame["rank_12m"] > outside_top]
    frame = frame.sort_values(["fmom", "rank_change"], ascending=False).head(TOP_STORED)
    return frame[["fmom", "rank_12m", "rank_change", "op_margin_chg"]].assign(score=frame["fmom"])


@category("emerging_sp400", "S&P 400 Emerging Leaders", "Fundamentals", "sp400",
          "Top-fifth Fundamental Momentum names whose 12-month return rank is rising but still outside the top 25.",
          lookback_sessions=280)
def emerging_sp400(ctx: Context) -> pd.DataFrame:
    return _emerging(ctx, "sp400")


def _rerating(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe, multiples=True)
    if frame.empty or "ps_chg" not in frame:
        return pd.DataFrame(columns=["score"])
    frame = frame[(frame["ni_ttm_yoy"] > 0) & (frame["rev_ttm_yoy"] > 0)].dropna(subset=["ps_chg"])
    frame = frame.sort_values("ps_chg", ascending=False).head(TOP_STORED)
    return frame[["ps_chg", "ps", "ni_ttm_yoy", "rev_ttm_yoy"]].assign(score=frame["ps_chg"])


@category("rerating_sp500", "S&P 500 Re-rating", "Fundamentals", "sp500",
          "Revenue and earnings growing, ranked by how much the price-to-sales multiple expanded over the year.",
          lookback_sessions=260)
def rerating_sp500(ctx: Context) -> pd.DataFrame:
    return _rerating(ctx, "sp500")


def _shrinkers(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    frame = frame[(frame["shares_yoy"] <= -0.03) & (frame["fcf_ttm"] > 0)]
    frame = frame.sort_values("shares_yoy").head(TOP_STORED)
    return frame[["shares_yoy", "buybacks_ttm", "fcf_margin"]].assign(score=-frame["shares_yoy"])


@category("shrinkers_sp500", "S&P 500 Share Shrinkers", "Fundamentals", "sp500",
          "Diluted share count down 3% or more over the year with positive free cash flow; biggest shrinkers first.",
          lookback_sessions=0)
def shrinkers_sp500(ctx: Context) -> pd.DataFrame:
    return _shrinkers(ctx, "sp500")


@category("emergingall_sp400", "S&P 400 Improving Fundamentals & Rank", "Fundamentals", "sp400",
          "Like S&P 400 Emerging Leaders but without leaving out the top 25 by 12-month return: top-fifth Fundamental "
          "Momentum names whose 12-month return rank is rising, ordered by fundamental score.",
          lookback_sessions=280)
def emergingall_sp400(ctx: Context) -> pd.DataFrame:
    return _emerging(ctx, "sp400", outside_top=None)
