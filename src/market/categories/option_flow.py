"""Option-flow categories (Lab, PLAN-signals §3), from `docs/research/01-option-flow.md`.

Of eleven option features tested on S&P 500 / 400 names (2024-11 → 2026-10, first year to choose,
second to check), two are kept, both borderline on two years of data:

  * **implied vol far above realized vol** (top decile of 30-day IV ÷ 20-day realized vol) lagged SPY
    by ~1% over the next 21 sessions in both halves — the option market pricing risk the stock hasn't
    shown yet. Used two ways:
      - `ivrich_sp900` — the warning list itself (a short-candidate list; long, it is expected to lag);
      - the S&P 500 / 400 Leaders and S&P 500 Rank Momentum lists, skipping warned names.
  * **an inverted IV term structure** (30-day IV above long-dated IV: near-term fear) beat names with
    a steep upward term structure by ~1% a month in both halves → `ivinverted_sp900`.

Pending acquisitions crowd the raw top decile (their price is pinned, so realized vol collapses while
the options keep some), so names with 20-day realized vol under MIN_RV are left out before ranking.
The effect holds without them (research robustness table: −0.7% in-sample, −1.5% out-of-sample).

Unusual call volume, put/call ratios and skew did not hold up and are not used. Option history
starts 2024-10, so these categories start ~2024-11; before that they are empty, not unfiltered.
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED, _leaders, _rank_momentum
from market.categories.registry import Context, category, source
from market.data.option_flow import feature_panel

WARN_DECILE = 0.90            # top decile of IV ÷ realized vol among liquid S&P 500 / 400 names that day
MIN_RV = 0.15                 # below this 20-day realized vol a name is treated as deal-pinned and skipped


class OptionFlow:
    """Option-flow features by session, for liquid names (≥ 500 contracts a day on average)."""

    def __init__(self, con, panel):
        frame = feature_panel(con, panel)
        frame = frame[frame["liquid"].fillna(False).astype(bool)]
        self.by_date = {d: g.set_index("security_id") for d, g in frame.groupby("date")}
        self.start = min(self.by_date) if self.by_date else None

    def on(self, as_of: pd.Timestamp) -> pd.DataFrame | None:
        return self.by_date.get(as_of)


@source("option_flow")
def _load(con, panel) -> OptionFlow:
    return OptionFlow(con, panel)


def iv_warnings(ctx: Context) -> pd.DataFrame | None:
    """Liquid S&P 500 / 400 names on `as_of` with iv_rv and its cross-sectional percentile; None before data."""
    flow = ctx.source("option_flow").on(ctx.as_of)
    if flow is None:
        return None
    ids = sorted(set(ctx.members("sp500")) | set(ctx.members("sp400")))
    frame = flow.reindex(ids)[["iv_rv", "rv20", "term"]].dropna(subset=["iv_rv"])
    frame = frame[frame["rv20"] >= MIN_RV]
    return frame.assign(iv_rv_pct=frame["iv_rv"].rank(pct=True))


@category("ivrich_sp900", "Option-Implied Risk", "Option flow", "sp900",
          "S&P 500 / 400 names whose 30-day implied volatility is furthest above their 20-day realized "
          "volatility (top decile, liquid options, realized vol ≥ 15%). A warning list: these lagged SPY by ~1% a month.",
          lookback_sessions=0, stage="lab")
def ivrich_sp900(ctx: Context) -> pd.DataFrame:
    frame = iv_warnings(ctx)
    if frame is None:
        return pd.DataFrame(columns=["score"])
    frame = frame[frame["iv_rv_pct"] >= WARN_DECILE].sort_values("iv_rv", ascending=False).head(TOP_STORED)
    return frame.assign(score=frame["iv_rv"])


def _skip_warned(ctx: Context, ranked: pd.DataFrame) -> pd.DataFrame:
    frame = iv_warnings(ctx)
    if frame is None:
        return pd.DataFrame(columns=["score"])
    pct = frame["iv_rv_pct"].reindex(ranked.index)
    kept = ranked[~(pct >= WARN_DECILE)]
    return kept.assign(iv_rv=frame["iv_rv"].reindex(kept.index)).head(TOP_STORED)


@category("mom12iv_sp500", "S&P 500 Leaders, IV Filter", "Option flow", "sp500",
          "S&P 500 Leaders, skipping names in the top decile of implied ÷ realized volatility "
          "(the Option-Implied Risk warning).", lookback_sessions=280, stage="lab")
def mom12iv_sp500(ctx: Context) -> pd.DataFrame:
    return _skip_warned(ctx, _leaders(ctx, ctx.members("sp500"), keep=30))


@category("mom12iv_sp400", "S&P 400 Leaders, IV Filter", "Option flow", "sp400",
          "S&P 400 Leaders, skipping names in the top decile of implied ÷ realized volatility.",
          lookback_sessions=280, stage="lab")
def mom12iv_sp400(ctx: Context) -> pd.DataFrame:
    return _skip_warned(ctx, _leaders(ctx, ctx.members("sp400"), keep=30))


@category("rankmomiv_sp500", "S&P 500 Rank Momentum, IV Filter", "Option flow", "sp500",
          "S&P 500 Rank Momentum, skipping names in the top decile of implied ÷ realized volatility.",
          lookback_sessions=280, stage="lab")
def rankmomiv_sp500(ctx: Context) -> pd.DataFrame:
    return _skip_warned(ctx, _rank_momentum(ctx, ctx.members("sp500"), keep=30))


@category("ivinverted_sp900", "Inverted Option Term Structure", "Option flow", "sp900",
          "S&P 500 / 400 names whose 30-day implied volatility is furthest above their long-dated implied "
          "volatility (near-term fear; liquid options, realized vol ≥ 15%). These beat SPY over the next month.",
          lookback_sessions=0, stage="lab")
def ivinverted_sp900(ctx: Context) -> pd.DataFrame:
    frame = iv_warnings(ctx)
    if frame is None:
        return pd.DataFrame(columns=["score"])
    frame = frame.dropna(subset=["term"]).sort_values("term", ascending=False).head(TOP_STORED)
    return frame.assign(score=frame["term"])
