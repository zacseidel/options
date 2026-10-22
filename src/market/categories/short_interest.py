"""Short-interest categories (Lab, PLAN-signals §9), from `docs/research/08-short-interest.md`.

Research (2022-10 → 2026-10, vs the average member): stocks with the most **days to cover** (short
interest ÷ average daily volume) lagged in both indexes and both halves (top vs bottom fifth: about −2%
to −3% over 63 sessions), and the gap was widest among momentum leaders (S&P 500 top 50: −17% over 126
sessions in 2025–26). Short interest as a share of the company and its month-on-month change showed
nothing consistent. So the Leaders list is rebuilt skipping heavily shorted names.

Strategy test from 2022-11: S&P 500 Leaders top 5 skipping the top fifth of days to cover returned 68% a
year (Sharpe 1.07) vs 60% (0.96) unfiltered, and 116% vs 90% in 2025–26 → kept. The same filter on S&P 400
Leaders (23% vs 32%) and S&P 500 Rank Momentum (53% vs 55%) made them worse → dropped.

A reading counts from its `available` date (settlement + 8 business days) and for 45 days after its
settlement; names without a recent reading are kept.
"""

from __future__ import annotations

import pandas as pd

from market.categories.momentum import TOP_STORED, _leaders
from market.categories.registry import Context, category, source, with_exclusions

CROWDED = 0.80                 # top fifth of days to cover among the index's members that day
MAX_AGE_DAYS = 45


class ShortInterest:
    def __init__(self, con, panel):
        si = con.execute("SELECT security_id, settlement_date, days_to_cover, available FROM short_interest").df()
        si["settlement_date"] = pd.to_datetime(si["settlement_date"])
        si["available"] = pd.to_datetime(si["available"])
        self.si = si.sort_values("available")
        self._memo: dict[pd.Timestamp, pd.DataFrame] = {}

    def on(self, when: pd.Timestamp) -> pd.DataFrame:
        """Latest published reading per security on `when` (index security_id)."""
        if when not in self._memo:
            known = self.si[self.si["available"] <= when].drop_duplicates("security_id", keep="last")
            known = known[(when - known["settlement_date"]).dt.days <= MAX_AGE_DAYS]
            self._memo[when] = known.set_index("security_id")
        return self._memo[when]


@source("short_interest")
def _load(con, panel) -> ShortInterest:
    return ShortInterest(con, panel)


def crowding(si: ShortInterest, as_of: pd.Timestamp, member_ids) -> pd.DataFrame:
    """Days to cover and its percentile among `member_ids` on `as_of` (`crowded` = top fifth). Shared by the
    category and the newsfeed's filter explanations."""
    dtc = si.on(as_of)["days_to_cover"].reindex(list(member_ids)).dropna()
    pct = dtc.rank(pct=True)
    return pd.DataFrame({"days_to_cover": dtc, "dtc_pct": pct, "crowded": pct >= CROWDED})


def _skip_crowded(ctx: Context, universe: str, ranked: pd.DataFrame) -> pd.DataFrame:
    table = crowding(ctx.source("short_interest"), ctx.as_of, ctx.members(universe))
    dtc = table["days_to_cover"]
    if dtc.empty:
        return pd.DataFrame(columns=["score"])                 # before short-interest history
    crowded = table[table["crowded"]].reindex(ranked.index).dropna(subset=["crowded"])
    reasons = pd.Series({sid: crowded_reason(r) for sid, r in crowded.iterrows()}, dtype=object)
    return with_exclusions(ranked.assign(days_to_cover=dtc.reindex(ranked.index)), reasons, TOP_STORED)


def crowded_reason(r) -> str:
    return f"heavily shorted: {r['days_to_cover']:.1f} days to cover (top {max(1, round(100 - r['dtc_pct'] * 100))}%)"


@category("mom12si_sp500", "S&P 500 Leaders, Short-Interest Filter", "Short interest", "sp500",
          "S&P 500 Leaders, skipping names in the top fifth of days to cover (short interest ÷ average daily "
          "volume) among S&P 500 members.", lookback_sessions=280)
def mom12si_sp500(ctx: Context) -> pd.DataFrame:
    return _skip_crowded(ctx, "sp500", _leaders(ctx, ctx.members("sp500"), keep=30))
