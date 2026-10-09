"""One lazily built bundle of Congress and 13F signals shared by every report date of a run."""

from __future__ import annotations

from functools import cached_property

import pandas as pd

from market.data.securities import STOCK_TYPES, map_tickers, ticker_map
from market.smartmoney import congress as congress_mod
from market.smartmoney import hedge as hedge_mod
from market.smartmoney import ledgers
from market.store.panel import Panel


class SmartMoney:
    congress_start = congress_mod.SIGNAL_START

    def __init__(self, con, panel: Panel):
        self.panel = panel
        self.history = ticker_map(con)
        self.stocks = self.history[self.history["type"].isin(STOCK_TYPES)]

    @cached_property
    def congress(self) -> congress_mod.CongressSignals:
        data = congress_mod.build(ledgers.congress_frame(), self.panel, self.history)
        return congress_mod.CongressSignals(data)

    @cached_property
    def hedge(self) -> hedge_mod.HedgeSignals:
        return hedge_mod.load_signals()

    def security_ids(self, tickers, as_of: pd.Timestamp) -> pd.Series:
        tickers = pd.Series(list(tickers))
        return map_tickers(self.stocks, tickers, pd.Series([as_of] * len(tickers)))
