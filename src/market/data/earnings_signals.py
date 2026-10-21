"""Earnings-event features (PLAN-signals §6): the market's reaction to each announcement.

For an 8-K 2.02 accepted at time t (US/Eastern), day 0 is the first session that can react: the same
session if t is before 16:00 on a trading day, else the next. The event is known after the close of
day +1 (`signal_date`), so nothing here uses later prices. Features:

  ear        total return day −1 close → day +1 close, minus SPY's (earnings-announcement return)
  gap        day 0 open vs day −1 close (split-adjusted)
  held       day +1 close vs day 0 open — did the gap hold through the next session?
  vol_ratio  day 0 volume ÷ mean of the prior 20 sessions
  pre_21     return over the 21 sessions before day −1 (run-up into the report)
  sue, rev_sue  standardized unexpected EPS / revenue from the 10-Q / 10-K, only if it was filed by the
             signal date (often it isn't: the 10-Q can follow the press release by weeks)
"""

from __future__ import annotations

from datetime import time as clock

import numpy as np
import pandas as pd

from market.data.fundamental_metrics import Fundamentals
from market.store.panel import Panel

CLOSE = clock(16, 0)


def reaction_session(panel: Panel, accepted: pd.Timestamp) -> pd.Timestamp | None:
    day = pd.Timestamp(accepted.date())
    pos = panel.sessions.searchsorted(day)
    if pos < len(panel.sessions) and panel.sessions[pos] == day and accepted.time() >= CLOSE:
        pos += 1                                   # after the close: the next session reacts
    return panel.sessions[pos] if pos < len(panel.sessions) else None


def security_for_cik(con, panel: Panel) -> dict[int, str]:
    """One security per company: the most traded share class."""
    sec = con.execute("SELECT security_id, cik FROM securities WHERE cik IS NOT NULL AND type IN ('CS', 'ADRC')").df()
    sec = sec[sec["cik"].astype(str).str.isdigit() & sec["security_id"].isin(panel.close.columns)]
    dv = (panel.raw_close * panel.volume).tail(250).mean()
    sec["dv"] = sec["security_id"].map(dv).fillna(0)
    sec = sec.sort_values("dv", ascending=False).drop_duplicates("cik")
    return dict(zip(sec["cik"].astype(int), sec["security_id"]))


def events(con, panel: Panel, fund: Fundamentals | None, spy: str) -> pd.DataFrame:
    raw = con.execute("SELECT cik, accn, accepted FROM earnings_events ORDER BY accepted").df()
    sid_of = security_for_cik(con, panel)
    raw["security_id"] = raw["cik"].map(sid_of)
    raw = raw.dropna(subset=["security_id"])
    sessions = panel.sessions
    rows = []
    tr, close, opn, vol = panel.tr, panel.close, panel.open, panel.volume
    vol_mean = vol.shift(1).rolling(20, min_periods=15).mean()
    for cik, accn, accepted, sid in raw.itertuples(index=False):
        d0 = reaction_session(panel, pd.Timestamp(accepted))
        if d0 is None:
            continue
        i = sessions.get_loc(d0)
        if i < 22 or i + 1 >= len(sessions):
            continue
        before, after = sessions[i - 1], sessions[i + 1]
        if pd.isna(tr.at[before, sid]) or pd.isna(tr.at[after, sid]) or pd.isna(opn.at[d0, sid]):
            continue
        ret = tr.at[after, sid] / tr.at[before, sid] - 1
        bench = tr.at[after, spy] / tr.at[before, spy] - 1
        rows.append({
            "cik": cik, "accn": accn, "security_id": sid, "accepted": accepted, "day0": d0, "date": after,
            "ear": ret - bench,
            "gap": opn.at[d0, sid] / close.at[before, sid] - 1,
            "held": close.at[after, sid] / opn.at[d0, sid] - 1,
            "vol_ratio": vol.at[d0, sid] / vol_mean.at[d0, sid] if vol_mean.at[d0, sid] > 0 else np.nan,
            "pre_21": tr.at[before, sid] / tr.at[sessions[i - 22], sid] - 1,
        })
    frame = pd.DataFrame(rows)
    if fund is not None and not frame.empty:
        frame = frame.join(_surprise(fund, frame), how="left")
    # Several 2.02 8-Ks for one reaction (an amendment, a same-day re-file): keep the first.
    return frame.drop_duplicates(["security_id", "day0"]).reset_index(drop=True)


def _surprise(fund: Fundamentals, frame: pd.DataFrame) -> pd.DataFrame:
    """SUE for the quarter the announcement reported, if its filing was public by the signal date."""
    st = fund.states[["cik", "end", "effective", "sue", "rev_sue"]]
    merged = frame[["cik", "day0", "date"]].reset_index().merge(st, on="cik", how="left")
    ok = (merged["end"] < merged["day0"]) & (merged["end"] >= merged["day0"] - pd.Timedelta(days=120)) \
        & (merged["effective"] <= merged["date"])
    best = merged[ok].sort_values("end").drop_duplicates("index", keep="last").set_index("index")
    return best[["sue", "rev_sue"]]
