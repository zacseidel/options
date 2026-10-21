"""Insider-buying categories (Lab, PLAN-signals §7), from `docs/research/04-insiders.md`.

Insider purchases (Form 4, code P, officers and directors, ≥ $10k) at S&P 500 / 400 members, as filed.
Insiders buy because they expect the company to be worth more, but also to signal confidence during a
turnaround, so the cluster list is split by fundamentals as filed (S&P 500 / 400 Fundamental Momentum):

  * `insider_clusters_sp900`   — a cluster forms: a 2nd insider buys within 30 days;
  * `insider_quality_sp900`    — clusters at companies in the top half of Fundamental Momentum;
  * `insider_turnaround_sp900` — clusters at companies in the bottom half;
  * `insider_csuite_sp900`     — a CEO / CFO / COO / President buys ≥ $250k (first buy in 30 days).

Each event is listed once, on the first report after it became public, so a fixed hold opens one lot.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from market.categories.fundamentals import fmom_score
from market.categories.registry import Context, category, source
from market.data.insider_signals import events

CSUITE_MIN = 250_000
QUALITY = 0.5
FEATURES = ["insiders_30d", "value_30d", "names"]


@source("insiders")
def _load(con, panel) -> pd.DataFrame:
    return events(con, panel)


def _new_events(ctx: Context) -> pd.DataFrame:
    """Events that became public after the previous report's as-of session, up to this one's."""
    ev = ctx.source("insiders")
    previous = ctx.report_date - timedelta(days=3 if ctx.report_date.weekday() == 4 else 4)
    prev_as_of = ctx.panel.session_on_or_before(previous - timedelta(days=1))
    part = ev[(ev["date"] > prev_as_of) & (ev["date"] <= ctx.as_of)]
    ids = set(ctx.members("sp500")) | set(ctx.members("sp400"))
    return part[part["security_id"].isin(ids)].set_index("security_id")


def _fmom(ctx: Context, ids: list[str]) -> pd.Series:
    """Fundamental Momentum as filed by `as_of`, ranked within each name's own index."""
    fund = ctx.source("fundamentals")
    ids = list(dict.fromkeys(ids))
    out = pd.Series(dtype=float)
    for universe in ("sp500", "sp400"):
        members = ctx.members(universe)
        mine = [s for s in ids if s in set(members)]
        if mine:
            out = pd.concat([out, fmom_score(fund.on(ctx.as_of, members)).reindex(mine)])
    return out[~out.index.duplicated()]          # a name can be in both indexes on a switch day


def _listed(frame: pd.DataFrame, extra: dict | None = None) -> pd.DataFrame:
    frame = frame.sort_values("value_30d", ascending=False)
    frame = frame[~frame.index.duplicated()]
    cols = FEATURES + list((extra or {}).keys())
    return frame.assign(**(extra or {}))[cols].assign(score=frame["value_30d"])


def _clusters(ctx: Context) -> pd.DataFrame:
    ev = _new_events(ctx)
    ev = ev[ev["cluster_start"]]
    return ev.assign(fmom=_fmom(ctx, list(ev.index)).reindex(ev.index)) if not ev.empty else ev.assign(fmom=[])


@category("insider_clusters_sp900", "Insider Clusters", "Insiders", "sp900",
          "S&P 500 / 400 companies where a second officer or director bought shares on the open market within "
          "30 days (each ≥ $10k), listed when the cluster's Form 4 is filed.", lookback_sessions=5, stage="lab")
def insider_clusters_sp900(ctx: Context) -> pd.DataFrame:
    ev = _clusters(ctx)
    return _listed(ev, {"fmom": ev["fmom"]}) if not ev.empty else pd.DataFrame(columns=["score"])


@category("insider_quality_sp900", "Insider Clusters, Quality", "Insiders", "sp900",
          "Insider Clusters at companies in the top half of their index's Fundamental Momentum (margins and "
          "earnings improving, as filed).", lookback_sessions=5, stage="lab")
def insider_quality_sp900(ctx: Context) -> pd.DataFrame:
    ev = _clusters(ctx)
    ev = ev[ev["fmom"] >= QUALITY] if not ev.empty else ev
    return _listed(ev, {"fmom": ev["fmom"]}) if not ev.empty else pd.DataFrame(columns=["score"])


@category("insider_turnaround_sp900", "Insider Clusters, Turnaround", "Insiders", "sp900",
          "Insider Clusters at companies in the bottom half of their index's Fundamental Momentum: insiders "
          "buying while the numbers are deteriorating.", lookback_sessions=5, stage="lab")
def insider_turnaround_sp900(ctx: Context) -> pd.DataFrame:
    ev = _clusters(ctx)
    ev = ev[ev["fmom"] < QUALITY] if not ev.empty else ev
    return _listed(ev, {"fmom": ev["fmom"]}) if not ev.empty else pd.DataFrame(columns=["score"])


@category("insider_csuite_sp900", "C-Suite Buys", "Insiders", "sp900",
          "S&P 500 / 400 companies whose CEO, CFO, COO or President bought ≥ $250k on the open market "
          "(first insider buy in 30 days).", lookback_sessions=5, stage="lab")
def insider_csuite_sp900(ctx: Context) -> pd.DataFrame:
    ev = _new_events(ctx)
    ev = ev[ev["csuite"] & ev["first_buy"] & (ev["value_today"] >= CSUITE_MIN)]
    return _listed(ev) if not ev.empty else pd.DataFrame(columns=["score"])
