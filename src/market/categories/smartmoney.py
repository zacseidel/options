"""Smart-money categories: what the best Congress traders and 13F funds are buying.

Each is a pure function of the report's Context; the scoring lives in market.smartmoney and
uses only disclosures public by `as_of`. Results are keyed by ticker there and mapped to
security ids here; names we can't price (funds, crypto trusts, unlisted) are skipped before
ranking so a slot is never left empty by an unpriceable name.
"""

from __future__ import annotations

import pandas as pd

from market.categories.registry import Context, category

TOP_STORED = 10


def _ranked(ctx: Context, frame: pd.DataFrame, by_security: bool) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["score"])
    if not by_security:
        ids = ctx.signals.security_ids(frame.index, ctx.as_of)
        frame = frame.assign(_sid=ids.to_numpy()).dropna(subset=["_sid"])
        frame = frame[~frame["_sid"].duplicated()].set_index("_sid")
        frame.index.name = None
    priced = ctx.panel.close.loc[ctx.as_of].reindex(frame.index).notna()
    return frame[priced.to_numpy()].head(TOP_STORED)


@category("congress_buys", "Congress Top-5 Buys", "Congress", "all",
          "Purchases disclosed in the last 120 days by the 5 members with the best follow-the-disclosure "
          "alpha (point-in-time), scored by share of each member's recent buying.",
          lookback_sessions=0)
def congress_buys(ctx: Context) -> pd.DataFrame:
    if ctx.as_of < ctx.signals.congress_start:
        return pd.DataFrame(columns=["score"])
    return _ranked(ctx, ctx.signals.congress.new_buys(ctx.as_of), by_security=True)


@category("congress_holdings", "Congress Top-5 Holdings", "Congress", "all",
          "Names the 5 best Congress traders still hold (bought, no sale disclosed), by share of each "
          "member's open book. Entered only after the disclosure is public.",
          lookback_sessions=0)
def congress_holdings(ctx: Context) -> pd.DataFrame:
    if ctx.as_of < ctx.signals.congress_start:
        return pd.DataFrame(columns=["score"])
    return _ranked(ctx, ctx.signals.congress.holdings(ctx.as_of), by_security=True)


@category("hedge_buys", "13F Skilled-Fund Buys", "Hedge funds", "all",
          "New positions in the latest 13F of the top 200 funds by follow-the-filing alpha "
          "(point-in-time), scored by Σ fund alpha × hit rate × position weight.",
          lookback_sessions=0)
def hedge_buys(ctx: Context) -> pd.DataFrame:
    return _ranked(ctx, ctx.signals.hedge.new_buys(ctx.as_of), by_security=False)


@category("hedge_drivers", "13F Alpha Drivers", "Hedge funds", "all",
          "Names that contributed most to the top 200 funds' alpha over their completed holding periods, "
          "among names those funds still hold.",
          lookback_sessions=0)
def hedge_drivers(ctx: Context) -> pd.DataFrame:
    return _ranked(ctx, ctx.signals.hedge.drivers(ctx.as_of), by_security=False)
