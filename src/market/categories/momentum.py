"""Momentum-report categories, ported from zacseidel/momentum (ranking.py) as pure functions.

Prices are split-adjusted closes (the momentum repo used Polygon `adjusted=true`), so picks
can be checked for parity against its live tables.
"""

from __future__ import annotations

import math

import pandas as pd

from market.categories.registry import Context, category

TOP_STORED = 10


def _leaders(ctx: Context, ids: list[str]) -> pd.DataFrame:
    """12-month return leaders whose rank is improving or steady vs. one month ago."""
    px = ctx.closes(ids, "now", "1w", "1m", "12m", "13m").dropna()
    current = px["now"] / px["12m"] - 1
    previous = px["1m"] / px["13m"] - 1
    frame = pd.DataFrame({
        "return_12m": current,
        "return_12m_prior": previous,
        "return_1w": px["now"] / px["1w"] - 1,
        "rank_12m": current.rank(ascending=False, method="min"),
        "rank_12m_prior": previous.rank(ascending=False, method="min"),
    })
    frame["rank_change"] = frame["rank_12m_prior"] - frame["rank_12m"]
    frame = frame[frame["rank_12m"] <= frame["rank_12m_prior"]]
    frame = frame.sort_values("return_12m", ascending=False).head(TOP_STORED)
    return frame.assign(score=frame["return_12m"])


@category("mom12_sp500", "S&P 500 Leaders", "Momentum", "sp500",
          "Highest 12-month return among S&P 500 members whose 12-month rank is improving or steady vs. a month ago.",
          lookback_sessions=280)
def mom12_sp500(ctx: Context) -> pd.DataFrame:
    return _leaders(ctx, ctx.members("sp500"))


@category("mom12_sp400", "S&P 400 Leaders", "Momentum", "sp400",
          "Highest 12-month return among S&P 400 members whose 12-month rank is improving or steady vs. a month ago.",
          lookback_sessions=280)
def mom12_sp400(ctx: Context) -> pd.DataFrame:
    return _leaders(ctx, ctx.members("sp400"))


@category("mom12_megacap", "Megacap Leaders", "Momentum", "sp500",
          "The 25 largest S&P 500 companies, ranked by 12-month return, rank improving or steady vs. a month ago.",
          lookback_sessions=280)
def mom12_megacap(ctx: Context) -> pd.DataFrame:
    return _leaders(ctx, list(ctx.largest("sp500", 25).index))


@category("laggards_mega10", "Megacap Laggards", "Reversion", "sp500",
          "Of the 10 largest S&P 500 companies, the 3 with the worst average rank of 3-, 6- and 12-month returns.",
          lookback_sessions=260)
def laggards_mega10(ctx: Context) -> pd.DataFrame:
    largest = ctx.largest("sp500", 10)
    px = ctx.closes(list(largest.index), "now", "3m", "6m", "12m").dropna()
    frame = pd.DataFrame({f"return_{p}": px["now"] / px[p] - 1 for p in ("3m", "6m", "12m")})
    for p in ("3m", "6m", "12m"):
        frame[f"rank_{p}"] = frame[f"return_{p}"].rank(ascending=False, method="min")
    frame["avg_rank"] = frame[["rank_3m", "rank_6m", "rank_12m"]].mean(axis=1)
    frame["market_cap"] = largest.reindex(frame.index)
    frame = frame.sort_values(["avg_rank", "return_12m"], ascending=[False, True]).head(3)
    return frame.assign(score=frame["avg_rank"])


@category("munger_top50", "Munger Dip", "Reversion", "sp500",
          "Of the 50 largest S&P 500 companies: a close below the 200-day SMA in the last 10 sessions, "
          "and the latest close back above the 10-day SMA. Ordered by size.",
          lookback_sessions=215)
def munger_top50(ctx: Context) -> pd.DataFrame:
    largest = ctx.largest("sp500", 50)
    sessions = ctx.panel.sessions
    end = sessions.get_loc(ctx.as_of)
    window = ctx.panel.close.iloc[max(0, end - 208): end + 1].reindex(columns=largest.index)   # 209 sessions
    # Fixed session windows; tolerate up to 10% missing observations, never reach further back.
    sma200 = window.rolling(200, min_periods=math.ceil(200 * 0.9)).mean()
    sma10 = window.rolling(10, min_periods=9).mean()
    recent_close, recent_sma = window.tail(10), sma200.tail(10)
    dipped = (recent_close < recent_sma).any()
    latest = window.iloc[-1]
    signal = dipped & latest.notna() & sma200.iloc[-1].notna() & (latest > sma10.iloc[-1])
    ids = signal[signal].index
    if len(ids) == 0:
        return pd.DataFrame(columns=["score"])
    last_dip = (recent_close[ids] < recent_sma[ids]).apply(lambda col: col[col].index.max())
    frame = pd.DataFrame({
        "price": latest[ids],
        "sma_200": sma200.iloc[-1][ids],
        "sma_10": sma10.iloc[-1][ids],
        "pct_vs_sma200": latest[ids] / sma200.iloc[-1][ids] - 1,
        "dip_date": last_dip.dt.date.astype(str),
        "market_cap": largest.reindex(ids),
    }).sort_values("market_cap", ascending=False)
    return frame.assign(score=frame["pct_vs_sma200"])


def _rank_momentum(ctx: Context, ids: list[str], periods: tuple[str, ...] = ("3m", "6m", "12m")) -> pd.DataFrame:
    """Best average rank of the given period returns across the whole index (1 = best)."""
    px = ctx.closes(ids, "now", "1w", *periods)
    px = px.dropna(subset=["now", *periods])
    frame = pd.DataFrame({f"return_{p}": px["now"] / px[p] - 1 for p in periods})
    for p in periods:
        frame[f"rank_{p}"] = frame[f"return_{p}"].rank(ascending=False, method="min")
    frame["avg_rank"] = frame[[f"rank_{p}" for p in periods]].mean(axis=1)
    frame["return_1w"] = px["now"] / px["1w"] - 1
    frame["universe_size"] = float(len(frame))
    # Best average rank first; the stronger longest-period return breaks ties.
    longest = f"return_{periods[-1]}"
    frame = frame.sort_values(["avg_rank", longest], ascending=[True, False]).head(TOP_STORED)
    return frame.assign(score=frame["avg_rank"])


@category("rankmom_sp500", "S&P 500 Rank Momentum", "Momentum", "sp500",
          "S&P 500 members with the best average rank of 3-, 6- and 12-month returns.",
          lookback_sessions=260)
def rankmom_sp500(ctx: Context) -> pd.DataFrame:
    return _rank_momentum(ctx, ctx.members("sp500"))


@category("rankmom_sp400", "S&P 400 Rank Momentum", "Momentum", "sp400",
          "S&P 400 members with the best average rank of 3-, 6- and 12-month returns.",
          lookback_sessions=260)
def rankmom_sp400(ctx: Context) -> pd.DataFrame:
    return _rank_momentum(ctx, ctx.members("sp400"))


@category("rankfast_sp500", "S&P 500 Fast Rank Momentum", "Momentum", "sp500",
          "S&P 500 members with the best average rank of 1-, 3- and 6-month returns.",
          lookback_sessions=135)
def rankfast_sp500(ctx: Context) -> pd.DataFrame:
    return _rank_momentum(ctx, ctx.members("sp500"), ("1m", "3m", "6m"))


@category("rankfast_sp400", "S&P 400 Fast Rank Momentum", "Momentum", "sp400",
          "S&P 400 members with the best average rank of 1-, 3- and 6-month returns.",
          lookback_sessions=135)
def rankfast_sp400(ctx: Context) -> pd.DataFrame:
    return _rank_momentum(ctx, ctx.members("sp400"), ("1m", "3m", "6m"))
