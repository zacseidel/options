"""Fundamental categories (Lab, PLAN-signals §5), from `docs/research/02-fundamentals.md`.

Fundamentals are EDGAR XBRL facts as first filed, usable from the day after filing
(`market.data.fundamental_metrics`). Research, 2022-10 → 2026-10 (rules chosen before 2025):

  * **margin expansion** (gross and operating margin vs a year earlier) led the next 3–6 months in
    both the S&P 500 and the S&P 400, in both halves; trailing **earnings growth** did in the S&P 500;
  * revenue / EPS acceleration, multiple expansion and share shrinkage showed nothing reliable;
  * steady growers (revenue up in most of the last 12 quarters) did well until 2025, then lagged.

`fmom_*` (Fundamental Momentum) ranks the survivors. The other families test the ideas that did not
survive the decile study but may still work as concentrated lists — compounders, re-rating,
shrinkers, emerging leaders — and the Reversion lists with a value-trap filter. All are Lab.
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED, _leaders, munger_top50
from market.categories.registry import Context, category, source
from market.data.fundamental_metrics import Fundamentals

FMOM_FEATURES = ["gross_margin_chg", "op_margin_chg", "ni_ttm_yoy"]
WEAK_PCT = 0.40                    # Reversion filter: skip names in the bottom 40% of Fundamental Momentum


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
          "year earlier) and trailing earnings growth, as filed.", lookback_sessions=0, stage="lab")
def fmom_sp500(ctx: Context) -> pd.DataFrame:
    return _fmom(ctx, "sp500")


@category("fmom_sp400", "S&P 400 Fundamental Momentum", "Fundamentals", "sp400",
          "S&P 400 members with growing revenue ranked by margin expansion and trailing earnings growth, as filed.",
          lookback_sessions=0, stage="lab")
def fmom_sp400(ctx: Context) -> pd.DataFrame:
    return _fmom(ctx, "sp400")


def _emerging(ctx: Context, universe: str) -> pd.DataFrame:
    """Top-quintile Fundamental Momentum whose 12-month price rank is improving but outside the top 25."""
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    frame = frame.assign(fmom=fmom_score(frame))
    leaders = _leaders(ctx, ctx.members(universe), keep=10_000)    # all names with an improving/steady rank
    ranked = ctx.closes(ctx.members(universe), "now", "12m").dropna()
    rank_12m = (ranked["now"] / ranked["12m"] - 1).rank(ascending=False)
    frame = frame.assign(rank_12m=rank_12m.reindex(frame.index),
                         rank_change=leaders["rank_change"].reindex(frame.index))
    frame = frame[(frame["fmom"] >= 0.8) & (frame["rank_12m"] > 25) & (frame["rank_change"] > 0)]
    frame = frame.sort_values(["fmom", "rank_change"], ascending=False).head(TOP_STORED)
    return frame[["fmom", "rank_12m", "rank_change", "op_margin_chg"]].assign(score=frame["fmom"])


@category("emerging_sp500", "S&P 500 Emerging Leaders", "Fundamentals", "sp500",
          "Top-fifth Fundamental Momentum names whose 12-month return rank is rising but still outside the top 25: "
          "an attempt to catch future leaders before the momentum lists do.", lookback_sessions=280, stage="lab")
def emerging_sp500(ctx: Context) -> pd.DataFrame:
    return _emerging(ctx, "sp500")


@category("emerging_sp400", "S&P 400 Emerging Leaders", "Fundamentals", "sp400",
          "Top-fifth Fundamental Momentum names whose 12-month return rank is rising but still outside the top 25.",
          lookback_sessions=280, stage="lab")
def emerging_sp400(ctx: Context) -> pd.DataFrame:
    return _emerging(ctx, "sp400")


def _compounders(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    steady = frame["rev_yoy_std_8q"] <= frame["rev_yoy_std_8q"].median()
    frame = frame[(frame["rev_up_12q"] >= 10) & steady & (frame["fcf_ttm"] > 0) & (frame["shares_yoy"] <= 0.01)]
    frame = frame.sort_values("rev_yoy_mean_8q", ascending=False).head(TOP_STORED)
    return frame[["rev_yoy_mean_8q", "rev_up_12q", "fcf_margin", "shares_yoy"]].assign(score=frame["rev_yoy_mean_8q"])


@category("compounders_sp500", "S&P 500 Steady Compounders", "Fundamentals", "sp500",
          "Revenue up year over year in at least 10 of the last 12 quarters, steadier growth than the median, "
          "positive free cash flow, no dilution; ranked by average growth over the last 8 quarters.",
          lookback_sessions=0, stage="lab")
def compounders_sp500(ctx: Context) -> pd.DataFrame:
    return _compounders(ctx, "sp500")


@category("compounders_sp400", "S&P 400 Steady Compounders", "Fundamentals", "sp400",
          "S&P 400 version of Steady Compounders.", lookback_sessions=0, stage="lab")
def compounders_sp400(ctx: Context) -> pd.DataFrame:
    return _compounders(ctx, "sp400")


def _rerating(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe, multiples=True)
    if frame.empty or "ps_chg" not in frame:
        return pd.DataFrame(columns=["score"])
    frame = frame[(frame["ni_ttm_yoy"] > 0) & (frame["rev_ttm_yoy"] > 0)].dropna(subset=["ps_chg"])
    frame = frame.sort_values("ps_chg", ascending=False).head(TOP_STORED)
    return frame[["ps_chg", "ps", "ni_ttm_yoy", "rev_ttm_yoy"]].assign(score=frame["ps_chg"])


@category("rerating_sp500", "S&P 500 Re-rating", "Fundamentals", "sp500",
          "Revenue and earnings growing, ranked by how much the price-to-sales multiple expanded over the year.",
          lookback_sessions=260, stage="lab")
def rerating_sp500(ctx: Context) -> pd.DataFrame:
    return _rerating(ctx, "sp500")


@category("rerating_sp400", "S&P 400 Re-rating", "Fundamentals", "sp400",
          "S&P 400 version of Re-rating.", lookback_sessions=260, stage="lab")
def rerating_sp400(ctx: Context) -> pd.DataFrame:
    return _rerating(ctx, "sp400")


def _shrinkers(ctx: Context, universe: str) -> pd.DataFrame:
    frame = _state(ctx, universe)
    if frame.empty:
        return pd.DataFrame(columns=["score"])
    frame = frame[(frame["shares_yoy"] <= -0.03) & (frame["fcf_ttm"] > 0)]
    frame = frame.sort_values("shares_yoy").head(TOP_STORED)
    return frame[["shares_yoy", "buybacks_ttm", "fcf_margin"]].assign(score=-frame["shares_yoy"])


@category("shrinkers_sp500", "S&P 500 Share Shrinkers", "Fundamentals", "sp500",
          "Diluted share count down 3% or more over the year with positive free cash flow; biggest shrinkers first.",
          lookback_sessions=0, stage="lab")
def shrinkers_sp500(ctx: Context) -> pd.DataFrame:
    return _shrinkers(ctx, "sp500")


@category("shrinkers_sp400", "S&P 400 Share Shrinkers", "Fundamentals", "sp400",
          "S&P 400 version of Share Shrinkers.", lookback_sessions=0, stage="lab")
def shrinkers_sp400(ctx: Context) -> pd.DataFrame:
    return _shrinkers(ctx, "sp400")


def _weak(ctx: Context, ids: list[str]) -> pd.Series:
    """True for names in the bottom WEAK_PCT of S&P 500 Fundamental Momentum (unknown → not weak)."""
    frame = _state(ctx, "sp500")
    pct = fmom_score(frame)
    return (pct.reindex(ids) < WEAK_PCT).fillna(False)


@category("laggards_mega10_fq", "Megacap Laggards, Fundamentals Filter", "Fundamentals", "sp500",
          "Megacap Laggards (worst average 3/6/12-month rank of the 10 largest), skipping companies in the bottom "
          "40% of S&P 500 Fundamental Momentum, so a value trap gives way to the next laggard.",
          lookback_sessions=260, stage="lab")
def laggards_mega10_fq(ctx: Context) -> pd.DataFrame:
    largest = ctx.largest("sp500", 10)
    px = ctx.closes(list(largest.index), "now", "3m", "6m", "12m").dropna()
    frame = pd.DataFrame({f"return_{p}": px["now"] / px[p] - 1 for p in ("3m", "6m", "12m")})
    for p in ("3m", "6m", "12m"):
        frame[f"rank_{p}"] = frame[f"return_{p}"].rank(ascending=False, method="min")
    frame["avg_rank"] = frame[["rank_3m", "rank_6m", "rank_12m"]].mean(axis=1)
    frame["market_cap"] = largest.reindex(frame.index)
    frame = frame.sort_values(["avg_rank", "return_12m"], ascending=[False, True])
    frame = frame[~_weak(ctx, list(frame.index))].head(3)
    return frame.assign(score=frame["avg_rank"])


@category("munger_top50_fq", "Munger Dip, Fundamentals Filter", "Fundamentals", "sp500",
          "Munger Dip, skipping companies in the bottom 40% of S&P 500 Fundamental Momentum.",
          lookback_sessions=215, stage="lab")
def munger_top50_fq(ctx: Context) -> pd.DataFrame:
    frame = munger_top50(ctx)
    if frame.empty:
        return frame
    return frame[~_weak(ctx, list(frame.index))]
