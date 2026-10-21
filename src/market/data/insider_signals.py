"""Insider-buying events for the companies we price (PLAN-signals §7).

A qualifying purchase is a Form 4 code-P buy of at least MIN_VALUE by an officer or director (10%
owners who are neither — usually funds — are left out, as in zacseidel/insiders). Purchases are
grouped by issuer and filing date; each group becomes an event dated the session on/after its
filing date (Form 4s can be filed after the close, so the market is assumed to learn at that day's
close and returns start at the next). Trailing-30-day features, all from filings made by then:

  insiders_30d   distinct insiders buying in the last 30 days (a cluster when ≥ 2)
  value_30d      dollars bought in the last 30 days
  csuite         a CEO / CFO / COO / President among today's buyers
  pct_increase   largest increase in a buyer's holding today (shares bought ÷ shares held before)
  planned        every purchase today was under a 10b5-1 plan
  first_buy      first event for the issuer in 30 days; `cluster_start` = the day a cluster forms
                 (2 insiders), `cluster3_start` = the day it reaches 3
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from market.data.earnings_signals import security_for_cik
from market.store.panel import Panel

MIN_VALUE = 10_000
WINDOW_DAYS = 30
CSUITE = r"(?i)\b(?:ceo|cfo|coo|chief executive|chief financial|chief operating|president)\b"


def purchases(con) -> pd.DataFrame:
    p = con.execute("SELECT * FROM insider_trades").df()
    p = p[(p["value"] >= MIN_VALUE) & (p["is_officer"] | p["is_director"])]
    p["filed"] = pd.to_datetime(p["filed"])
    p["held_before"] = (p["shares_after"] - p["shares"]).where(lambda s: s > 0)
    p["pct_increase"] = p["shares"] / p["held_before"]
    p["csuite"] = p["officer_title"].fillna("").str.contains(CSUITE, regex=True)
    return p


def events(con, panel: Panel) -> pd.DataFrame:
    p = purchases(con)
    sid_of = security_for_cik(con, panel)
    p["security_id"] = p["issuer_cik"].astype("int64").map(sid_of)
    p = p.dropna(subset=["security_id"])
    day = p.groupby(["security_id", "filed"]).agg(
        value=("value", "sum"), buyers=("owner_cik", "nunique"), csuite=("csuite", "any"),
        pct_increase=("pct_increase", "max"), planned=("plan_10b5_1", "all"),
        names=("owner_name", lambda s: ", ".join(sorted(set(s.dropna()))[:4]))).reset_index()
    rows = []
    for sid, g in day.groupby("security_id"):
        g = g.sort_values("filed")
        buys = p[p["security_id"] == sid][["filed", "owner_cik", "value"]]
        last_event = None
        prev_insiders = 0
        for r in g.itertuples(index=False):
            window = buys[(buys["filed"] > r.filed - pd.Timedelta(days=WINDOW_DAYS)) & (buys["filed"] <= r.filed)]
            insiders = window["owner_cik"].nunique()
            earlier = window[window["filed"] < r.filed]
            prev_insiders = earlier["owner_cik"].nunique()
            rows.append({
                "security_id": sid, "filed": r.filed, "value_today": r.value, "buyers_today": r.buyers,
                "insiders_30d": insiders, "value_30d": window["value"].sum(), "csuite": r.csuite,
                "pct_increase": r.pct_increase, "planned": r.planned, "names": r.names,
                "first_buy": last_event is None or (r.filed - last_event).days > WINDOW_DAYS,
                "cluster_start": insiders >= 2 and prev_insiders < 2,
                "cluster3_start": insiders >= 3 and prev_insiders < 3,
            })
            last_event = r.filed
    ev = pd.DataFrame(rows)
    if ev.empty:
        return ev
    pos = panel.sessions.searchsorted(ev["filed"])
    ok = pos < len(panel.sessions)
    ev = ev[ok].copy()
    ev["date"] = panel.sessions[pos[ok]]
    return ev.reset_index(drop=True)


def universe_mean_excess(panel: Panel, members: pd.DataFrame, dates: list[pd.Timestamp], bench: str,
                         horizons: tuple[int, ...]) -> pd.DataFrame:
    """Average excess return of every S&P 500 / 400 member over the same windows (a fair baseline:
    an equal-weight list of mid caps lags cap-weighted SPY on its own)."""
    tr = panel.tr
    values, b = tr.to_numpy(), tr[bench].to_numpy()
    out = {}
    for d in dates:
        live = members[(members["valid_from"] <= d) & (members["valid_to"] > d)]["security_id"].unique()
        cols = tr.columns.get_indexer(live)
        cols = cols[cols >= 0]
        i = panel.sessions.searchsorted(d, side="right")
        row = {}
        for h in horizons:
            if i + h >= len(panel.sessions):
                row[h] = np.nan
                continue
            r = values[i + h, cols] / values[i, cols] - 1
            row[h] = float(np.nanmean(r) - (b[i + h] / b[i] - 1))
        out[d] = row
    return pd.DataFrame(out).T
