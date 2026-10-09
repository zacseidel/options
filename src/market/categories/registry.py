"""Category registry and the shared context every category computes from.

A category is a pure function of a Context (one report date, one shared price panel) that
returns a ranked frame. It never reads the database itself, so any date can be recomputed
and the daily run and the 5-year backtest use the same code path.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from market.store.panel import Panel


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    group: str
    universe: str
    description: str
    compute: Callable[["Context"], pd.DataFrame]
    lookback_sessions: int                 # history needed before the first computable date

    @property
    def version(self) -> str:
        source = inspect.getsource(self.compute)
        return hashlib.sha1(source.encode()).hexdigest()[:10]


REGISTRY: dict[str, Category] = {}


def category(id: str, name: str, group: str, universe: str, description: str, lookback_sessions: int):
    def register(fn: Callable[["Context"], pd.DataFrame]) -> Callable[["Context"], pd.DataFrame]:
        REGISTRY[id] = Category(id, name, group, universe, description, fn, lookback_sessions)
        return fn
    return register


@dataclass
class Context:
    """Everything a category may read for one report date — nothing later than `as_of`."""

    report_date: date
    panel: Panel
    membership: pd.DataFrame               # universe, security_id, valid_from, valid_to
    caps: pd.DataFrame                     # sessions × security_id market caps
    securities: pd.DataFrame               # security_id → cik, name (index security_id)
    dollar_volume: pd.DataFrame            # sessions × security_id trailing 60-session mean
    _members_cache: dict = field(default_factory=dict)

    @property
    def as_of(self) -> pd.Timestamp:
        """Last session before the report date (reports publish before the open)."""
        return self.panel.session_on_or_before(self.report_date - timedelta(days=1))

    def members(self, universe: str) -> list[str]:
        """Point-in-time members on the report date (the universe sync runs first that day)."""
        if universe not in self._members_cache:
            when = pd.Timestamp(self.report_date)
            m = self.membership[self.membership["universe"] == universe]
            starts, ends = pd.to_datetime(m["valid_from"]), pd.to_datetime(m["valid_to"])
            live = m[(starts.isna() | (starts <= when)) & (ends.isna() | (ends > when))]
            self._members_cache[universe] = sorted(set(live["security_id"].dropna()))
        return self._members_cache[universe]

    def date_map(self) -> dict[str, pd.Timestamp]:
        """The momentum report's reference dates, each resolved to the session on or before."""
        base = pd.Timestamp(self.report_date - timedelta(days=1))
        nominal = {
            "now": base,
            "1w": base - pd.Timedelta(weeks=1),
            "1m": base - pd.DateOffset(months=1),
            "3m": base - pd.DateOffset(months=3),
            "6m": base - pd.DateOffset(months=6),
            "12m": base - pd.DateOffset(years=1),
            "13m": base - pd.DateOffset(years=1, months=1),
        }
        return {k: self.panel.session_on_or_before(v.date()) for k, v in nominal.items()}

    def largest(self, universe: str, n: int) -> pd.Series:
        """Top-n members by market cap as of `as_of`, one share class per company → cap (desc)."""
        ids = [s for s in self.members(universe) if s in self.caps.columns]
        caps = self.caps.loc[self.as_of, ids].dropna()
        frame = pd.DataFrame({"cap": caps})
        frame["cik"] = self.securities["cik"].reindex(frame.index).fillna(pd.Series(frame.index, index=frame.index))
        frame["dv"] = self.dollar_volume.loc[self.as_of].reindex(frame.index).fillna(0)
        # GOOG/GOOGL (and FOX/FOXA, NWS/NWSA) share one company cap: keep the more traded class.
        frame = frame.sort_values("dv", ascending=False).drop_duplicates("cik")
        return frame["cap"].sort_values(ascending=False).head(n)

    def closes(self, ids: list[str], *keys: str) -> pd.DataFrame:
        dates = self.date_map()
        return pd.DataFrame({k: self.panel.close.loc[dates[k]].reindex(ids) for k in keys})
