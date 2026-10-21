"""Post-earnings categories (Lab, PLAN-signals §6), from `docs/research/03-earnings.md`.

Research (17.9 k S&P 500 / 400 announcements, 2021-11 → 2026-10, rules chosen before 2025): **no
post-earnings drift**. No reaction or surprise measure survived; big positive reactions slightly
reversed, big negative ones kept falling before 2025 and bounced after. Drift is known to have faded in
large, well-covered stocks. The standard rule is kept as a Lab pair anyway, to build a live record:

  * `pead_up_sp900`   — reaction ≥ +5% vs SPY over day −1 → +1, the gap held, volume ≥ 2× normal;
  * `pead_down_sp900` — the mirror (≤ −5%), a short-candidate list for the shorts phase.

Each announcement is listed once, on the first report after its signal day (day +1), so a fixed hold
opens one lot per event.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from market.categories.registry import Context, category, source
from market.data.earnings_signals import events
from market.research.common import spy_id

EAR_MIN = 0.05
VOL_MIN = 2.0


@source("earnings")
def _load(con, panel) -> pd.DataFrame:
    ev = events(con, panel, None, spy_id(con))
    ev["date"] = pd.to_datetime(ev["date"])
    return ev


def _since_last_report(ctx: Context) -> pd.DataFrame:
    """Events whose signal day falls after the previous report's as-of session, up to this one's."""
    ev = ctx.source("earnings")
    previous = ctx.report_date - timedelta(days=3 if ctx.report_date.weekday() == 4 else 4)
    prev_as_of = ctx.panel.session_on_or_before(previous - timedelta(days=1))
    ids = set(ctx.members("sp500")) | set(ctx.members("sp400"))
    part = ev[(ev["date"] > prev_as_of) & (ev["date"] <= ctx.as_of)]
    return part[part["security_id"].isin(ids)].set_index("security_id")


def _ranked(frame: pd.DataFrame, ascending: bool) -> pd.DataFrame:
    frame = frame.sort_values("ear", ascending=ascending)
    frame = frame[~frame.index.duplicated()]
    return frame[["ear", "gap", "held", "vol_ratio"]].assign(score=frame["ear"])


@category("pead_up_sp900", "Strong Earnings Reactions", "Earnings", "sp900",
          "S&P 500 / 400 names that rose ≥ 5% vs SPY around their earnings release (day −1 → +1), held the gap "
          "and traded ≥ 2× normal volume. Research found no drift after these; kept to build a live record.",
          lookback_sessions=25, stage="lab")
def pead_up_sp900(ctx: Context) -> pd.DataFrame:
    ev = _since_last_report(ctx)
    return _ranked(ev[(ev["ear"] >= EAR_MIN) & (ev["held"] >= 0) & (ev["vol_ratio"] >= VOL_MIN)], ascending=False)


@category("pead_down_sp900", "Weak Earnings Reactions", "Earnings", "sp900",
          "S&P 500 / 400 names that fell ≥ 5% vs SPY around their earnings release, kept falling into day +1 and "
          "traded ≥ 2× normal volume. A short-candidate list.", lookback_sessions=25, stage="lab")
def pead_down_sp900(ctx: Context) -> pd.DataFrame:
    ev = _since_last_report(ctx)
    return _ranked(ev[(ev["ear"] <= -EAR_MIN) & (ev["held"] <= 0) & (ev["vol_ratio"] >= VOL_MIN)], ascending=True)
