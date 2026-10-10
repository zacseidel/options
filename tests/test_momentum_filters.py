from datetime import date

import numpy as np
import pandas as pd

from market.categories.momentum import STALL_WINDOW, _rsi, _sessions_since_high
from market.categories.registry import Context
from market.store.panel import Panel

SESSIONS = pd.bdate_range("2026-01-05", periods=200)


def ctx_for(closes: dict[str, list[float]]) -> Context:
    close = pd.DataFrame(closes, index=SESSIONS, dtype=float)
    ones = close * 0 + 1
    panel = Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                  volume=ones, tr=close / close.iloc[0], split_factor=ones)
    report = (SESSIONS[-1] + pd.offsets.BDay(1)).date()           # as_of = the last session
    return Context(report, panel, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())


def test_sessions_since_high_counts_from_the_window_peak():
    rising = list(np.arange(200.0) + 100)
    peaked = rising[:180] + [rising[179] - 1] * 20                 # last high 20 sessions ago
    ctx = ctx_for({"UP": rising, "OLD": peaked})
    since = _sessions_since_high(ctx, ["UP", "OLD"])
    assert since["UP"] == 0 and since["OLD"] == 20


def test_sessions_since_high_needs_coverage():
    thin = [np.nan] * (200 - STALL_WINDOW // 2) + [100.0] * (STALL_WINDOW // 2)
    since = _sessions_since_high(ctx_for({"THIN": thin}), ["THIN"])
    assert np.isnan(since["THIN"])


def test_rsi_extremes_and_midpoint():
    up = list(np.arange(200.0) + 100)                              # only gains → 100
    down = list(300 - np.arange(200.0))                            # only losses → 0
    zigzag = [100 + (i % 2) for i in range(200)]                   # equal gains and losses → 50
    rsi = _rsi(ctx_for({"UP": up, "DOWN": down, "ZIG": zigzag}), ["UP", "DOWN", "ZIG"])
    assert rsi["UP"] == 100 and rsi["DOWN"] < 1 and abs(rsi["ZIG"] - 50) < 5
