"""The in-memory price panel every category and evaluation reads (loaded once per run).

Wide frames indexed by session × security_id:
  close, open, high, low, vwap — split-adjusted (raw ÷ product of later split ratios)
  raw_close                    — as traded
  tr                           — total-return index: split-adjusted price with cash dividends
                                 reinvested on the ex-date (PLAN §2.5)
Adjusting on read means a new split never leaves stale rows behind (the momentum repo's
split-repair problem).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np
import pandas as pd

PRICE_FIELDS = ("open", "high", "low", "close", "vwap")


@dataclass
class Panel:
    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    vwap: pd.DataFrame
    raw_close: pd.DataFrame
    volume: pd.DataFrame
    tr: pd.DataFrame
    split_factor: pd.DataFrame

    @property
    def sessions(self) -> pd.DatetimeIndex:
        return self.close.index

    def session_on_or_before(self, when: date) -> pd.Timestamp | None:
        i = self.sessions.searchsorted(pd.Timestamp(when), side="right") - 1
        return self.sessions[i] if i >= 0 else None

    def session_on_or_after(self, when: date) -> pd.Timestamp | None:
        i = self.sessions.searchsorted(pd.Timestamp(when), side="left")
        return self.sessions[i] if i < len(self.sessions) else None


def split_factors(splits: pd.DataFrame, sessions: pd.DatetimeIndex, securities: pd.Index) -> pd.DataFrame:
    """factor[t, s] = product of (split_to / split_from) for s's splits with ex_date > t."""
    ratio = pd.DataFrame(1.0, index=sessions, columns=securities)
    for sid, ex_date, split_from, split_to in splits[["security_id", "ex_date", "split_from", "split_to"]].itertuples(index=False):
        if sid not in ratio.columns:
            continue
        pos = sessions.searchsorted(pd.Timestamp(ex_date), side="left")
        if pos < len(sessions):
            ratio.iat[pos, ratio.columns.get_loc(sid)] *= split_to / split_from
    # Product over strictly later sessions: reverse cumulative product, shifted one session.
    later = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    return later


def total_return_index(close: pd.DataFrame, dividends: pd.DataFrame, factor: pd.DataFrame) -> pd.DataFrame:
    """Daily (P_t + D_t) / P_{t-1} on split-adjusted prices, chained; starts at 1.0 per security."""
    div = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for sid, ex_date, amount in dividends[["security_id", "ex_date", "amount"]].itertuples(index=False):
        if sid not in div.columns:
            continue
        pos = close.index.searchsorted(pd.Timestamp(ex_date), side="left")
        if pos < len(close.index):
            div.iat[pos, div.columns.get_loc(sid)] += amount
    div = div / factor                                    # dividends in split-adjusted terms
    prev = close.ffill(limit=5).shift(1)                  # bridge short halts, not delistings
    growth = ((close + div) / prev).where(close.notna() & prev.notna())
    index = growth.fillna(1.0).cumprod()
    return index.where(close.notna())


def load_panel(
    con: duckdb.DuckDBPyConnection,
    start: date | None = None,
    end: date | None = None,
    securities: list[str] | None = None,
) -> Panel:
    where, params = ["TRUE"], []
    if start:
        where.append("date >= ?"); params.append(start)
    if end:
        where.append("date <= ?"); params.append(end)
    if securities:
        where.append(f"security_id IN ({','.join('?' * len(securities))})"); params.extend(securities)
    bars = con.execute(
        f"SELECT security_id, date, open, high, low, close, vwap, volume FROM bars_daily WHERE {' AND '.join(where)}", params
    ).df()
    # Factorize ids and dates once and scatter into numpy arrays — much faster than one pandas
    # pivot per field, and a plain object column index keeps .at/.loc lookups fast.
    sid_codes, sid_values = pd.factorize(bars["security_id"].to_numpy(dtype=object), sort=True)
    date_codes, date_values = pd.factorize(pd.to_datetime(bars["date"]).to_numpy(), sort=True)
    sessions = pd.DatetimeIndex(date_values)
    columns = pd.Index(list(sid_values), dtype=object)

    def wide_of(field: str) -> pd.DataFrame:
        grid = np.full((len(sessions), len(columns)), np.nan)
        grid[date_codes, sid_codes] = bars[field].to_numpy(dtype=float)
        return pd.DataFrame(grid, index=sessions, columns=columns)

    wide = {field: wide_of(field) for field in PRICE_FIELDS}

    splits = con.execute("SELECT security_id, ex_date, split_from, split_to FROM splits").df()
    dividends = con.execute("SELECT security_id, ex_date, amount FROM dividends WHERE kind IN ('CD', 'SC')").df()
    factor = split_factors(splits, sessions, columns)
    adjusted = {field: frame / factor for field, frame in wide.items()}
    return Panel(
        close=adjusted["close"], open=adjusted["open"], high=adjusted["high"], low=adjusted["low"],
        vwap=adjusted["vwap"], raw_close=wide["close"],
        volume=wide_of("volume"),
        tr=total_return_index(adjusted["close"], dividends, factor), split_factor=factor,
    )
