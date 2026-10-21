"""Dividend events from the stored dividends (PLAN-signals §8): initiations, raises, cuts, specials.

A regular dividend (kind CD) is compared with the company's previous regular dividend at the same
payment frequency; pairs with a split in between are skipped (a split changes the per-share amount).
Each event is dated by its declaration (the announcement; falls back to the ex-date).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GAP_DAYS = 730                       # no regular dividend for this long before → an initiation


def stored(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    div = con.execute("SELECT security_id, ex_date, declared, amount, kind, frequency FROM dividends").df()
    splits = con.execute("SELECT security_id, ex_date FROM splits").df()
    return div, splits


def events(div: pd.DataFrame, splits: pd.DataFrame, history_start: pd.Timestamp) -> pd.DataFrame:
    d = div.copy()
    d["ex_date"] = pd.to_datetime(d["ex_date"])
    d["frequency"] = pd.to_numeric(d["frequency"], errors="coerce").fillna(-1).astype(int)   # unknown = -1
    d["declared"] = pd.to_datetime(d["declared"], errors="coerce")
    d["date"] = d["declared"].where(d["declared"].notna() & (d["declared"] <= d["ex_date"]), d["ex_date"])
    reg = (d[d["kind"] == "CD"].sort_values(["security_id", "ex_date"])
           .drop_duplicates(["security_id", "ex_date"]).reset_index(drop=True))
    g = reg.groupby("security_id")
    prev_ex, prev_amt, prev_freq = g["ex_date"].shift(), g["amount"].shift(), g["frequency"].shift()
    gap = (reg["ex_date"] - prev_ex).dt.days
    # A split between two dividends: mark the first dividend on/after each split's ex-date.
    split_after = pd.Series(False, index=reg.index)
    if not splits.empty:
        sp = splits.assign(ex_date=pd.to_datetime(splits["ex_date"])).sort_values("ex_date")
        hit = pd.merge_asof(sp, reg.reset_index().sort_values("ex_date"), on="ex_date", by="security_id",
                            direction="forward").dropna(subset=["index"])
        split_after.loc[hit["index"].astype(int)] = True
    initiation = (prev_ex.isna() & (reg["ex_date"] >= history_start + pd.Timedelta(days=GAP_DAYS))) | (gap > GAP_DAYS)
    change = reg["amount"] / prev_amt - 1
    comparable = (gap <= GAP_DAYS) & (reg["frequency"] == prev_freq) & (prev_amt > 0) & ~split_after \
        & (change.abs() >= 0.01)
    out = pd.concat([
        reg[initiation].assign(type="initiation", change=np.nan),
        reg[comparable].assign(type=np.where(change[comparable] > 0, "raise", "cut"), change=change[comparable]),
        d[d["kind"] == "SC"].assign(type="special", change=np.nan),
    ])
    return out[["security_id", "date", "type", "change"]].reset_index(drop=True)
