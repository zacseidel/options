"""Dividend categories (Lab, PLAN-signals §8), from `docs/research/06-corporate-actions.md`.

Research (S&P 500 / 400, 2021-10 → 2026-10, vs the average member): companies **raising their regular
dividend by 10% or more** beat the average member by ~2% (before 2025) and ~3.5% (2025–26) over the next
126 sessions, dated by the announcement. As a strategy (total return, dividends reinvested) it slightly
beat SPY. Small raises lagged; cuts lagged badly (a short-side signal for the shorts phase).

Each raise is listed once, on the first report after its announcement, so a fixed hold opens one lot.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from market.categories.registry import Context, category, source
from market.data.dividend_signals import events, stored

RAISE_MIN = 0.10


@source("dividend_events")
def _load(con, panel) -> pd.DataFrame:
    div, splits = stored(con)
    ev = events(div, splits, pd.to_datetime(div["ex_date"]).min())
    ev["date"] = pd.to_datetime(ev["date"])
    return ev


@category("divraise_sp900", "Dividend Raisers", "Corporate actions", "sp900",
          "S&P 500 / 400 companies that announced a regular dividend at least 10% above the previous one "
          "(same frequency), listed once when announced.", lookback_sessions=5, stage="lab")
def divraise_sp900(ctx: Context) -> pd.DataFrame:
    ev = ctx.source("dividend_events")
    previous = ctx.report_date - timedelta(days=3 if ctx.report_date.weekday() == 4 else 4)
    prev_as_of = ctx.panel.session_on_or_before(previous - timedelta(days=1))
    ids = set(ctx.members("sp500")) | set(ctx.members("sp400"))
    part = ev[(ev["type"] == "raise") & (ev["change"] >= RAISE_MIN) & (ev["date"] > prev_as_of)
              & (ev["date"] <= ctx.as_of) & ev["security_id"].isin(ids)]
    part = part.sort_values("change", ascending=False).drop_duplicates("security_id").set_index("security_id")
    return part[["change"]].rename(columns={"change": "raise"}).assign(score=part["change"])
