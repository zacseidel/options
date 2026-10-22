"""Momentum-report categories, ported from zacseidel/momentum (ranking.py) as pure functions.

Prices are split-adjusted closes (the momentum repo used Polygon `adjusted=true`), so picks
can be checked for parity against its live tables.
"""

from __future__ import annotations

import math

import pandas as pd

from market.categories.registry import Context, category, with_exclusions

TOP_STORED = 10


def _leaders(ctx: Context, ids: list[str], keep: int = TOP_STORED) -> pd.DataFrame:
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
    frame = frame.sort_values("return_12m", ascending=False).head(keep)
    return frame.assign(score=frame["return_12m"])


@category("mom12_sp500", "S&P 500 Leaders", "Momentum", "sp500",
          "Highest 12-month return among S&P 500 members whose 12-month rank is improving or steady vs. a month ago.",
          lookback_sessions=280)
def mom12_sp500(ctx: Context) -> pd.DataFrame:
    return _leaders(ctx, ctx.members("sp500"))


# Isolated stall (ported from momentum10 ranking.py, where it is a report-only flag). A stock whose
# highest close of the last STALL_WINDOW sessions is more than STALL_SESSIONS sessions old has
# stalled. If at most ISOLATED_STALL_MAX of the unfiltered top 10 by 12-month return have stalled,
# the stall is isolated: stalled leaders are dropped, so the next unstalled leader takes the slot.
# More stalls than that are a broad market dip and the list is left alone.
STALL_WINDOW = 60
STALL_SESSIONS = 15
ISOLATED_STALL_MAX = 3


def _sessions_since_high(ctx: Context, ids: list[str], minimum_coverage: float = 0.90) -> pd.Series:
    """Sessions since each name's highest close in the stall window (NaN if too little history)."""
    end = ctx.panel.sessions.get_loc(ctx.as_of)
    window = ctx.panel.close.iloc[max(0, end - STALL_WINDOW + 1): end + 1].reindex(columns=ids)
    minimum = math.ceil(len(window) * minimum_coverage)
    out = {}
    for sid in ids:
        col = window[sid]
        if pd.isna(col.iloc[-1]) or col.notna().sum() < minimum:
            out[sid] = float("nan")
        else:
            out[sid] = float(len(col) - 1 - col.reset_index(drop=True).idxmax())
    return pd.Series(out, dtype=float)


@category("mom12stall_sp500", "S&P 500 Leaders, Isolated Stall", "Momentum", "sp500",
          "S&P 500 Leaders, skipping any leader with no new 60-session closing high for 15+ sessions when at "
          "most 3 of the top 10 by 12-month return have stalled (an isolated stall); broad stalls are ignored.",
          lookback_sessions=280)
def mom12stall_sp500(ctx: Context) -> pd.DataFrame:
    ids = ctx.members("sp500")
    px = ctx.closes(ids, "now", "12m").dropna()
    top10 = list((px["now"] / px["12m"] - 1).sort_values(ascending=False).head(10).index)
    leaders = _leaders(ctx, ids, keep=30)
    since = _sessions_since_high(ctx, sorted(set(top10) | set(leaders.index)))
    stalled = since > STALL_SESSIONS
    isolated = int(stalled.reindex(top10).fillna(False).sum()) <= ISOLATED_STALL_MAX
    leaders = leaders.assign(sessions_since_high=since.reindex(leaders.index),
                             stall_breadth=int(stalled.reindex(top10).fillna(False).sum()))
    skip = stalled.reindex(leaders.index).fillna(False) if isolated else pd.Series(False, index=leaders.index)
    reasons = pd.Series({sid: f"stalled: last 60-session high {since[sid]:.0f} sessions ago" for sid in leaders.index[skip]},
                        dtype=object)
    return with_exclusions(leaders, reasons, TOP_STORED)


def _rsi(ctx: Context, ids: list[str], period: int = 14, history: int = 150) -> pd.Series:
    """Wilder RSI on split-adjusted closes as of the report's as-of session."""
    end = ctx.panel.sessions.get_loc(ctx.as_of)
    closes = ctx.panel.close.iloc[max(0, end - history + 1): end + 1].reindex(columns=ids)
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    return rsi.iloc[-1].where(loss.iloc[-1] > 0, 100.0)


def _reasonable_growth(ctx: Context, universe: str) -> pd.DataFrame:
    """Top 12-month returns among members whose 14-day RSI is between 20 and 80."""
    ids = ctx.members(universe)
    px = ctx.closes(ids, "now", "12m").dropna()
    frame = pd.DataFrame({"return_12m": px["now"] / px["12m"] - 1})
    frame["rsi_14"] = _rsi(ctx, list(frame.index)).reindex(frame.index)
    frame = frame.sort_values("return_12m", ascending=False, kind="stable")
    band = (frame["rsi_14"] > 20) & (frame["rsi_14"] < 80)
    reasons = pd.Series({sid: f"RSI {rsi:.0f}, outside 20–80" if pd.notna(rsi) else "no RSI"
                         for sid, rsi in frame.loc[~band, "rsi_14"].items()}, dtype=object)
    return with_exclusions(frame.assign(score=frame["return_12m"]), reasons, TOP_STORED)


@category("rgrowth_sp500", "S&P 500 Reasonable Growth Leaders", "Momentum", "sp500",
          "Highest 12-month return among S&P 500 members whose 14-day RSI is above 20 and below 80.",
          lookback_sessions=280)
def rgrowth_sp500(ctx: Context) -> pd.DataFrame:
    return _reasonable_growth(ctx, "sp500")


@category("rgrowth_sp400", "S&P 400 Reasonable Growth Leaders", "Momentum", "sp400",
          "Highest 12-month return among S&P 400 members whose 14-day RSI is above 20 and below 80.",
          lookback_sessions=280)
def rgrowth_sp400(ctx: Context) -> pd.DataFrame:
    return _reasonable_growth(ctx, "sp400")


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


def _rank_momentum(ctx: Context, ids: list[str], periods: tuple[str, ...] = ("3m", "6m", "12m"),
                   keep: int = TOP_STORED) -> pd.DataFrame:
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
    frame = frame.sort_values(["avg_rank", longest], ascending=[True, False]).head(keep)
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
