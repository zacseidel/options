from datetime import date

import numpy as np
import pandas as pd

from market.evaluate.engine import build_nav
from market.methods.hold_rules import fixed_hold, price_exit, while_listed
from market.store.panel import Panel

SESSIONS = pd.bdate_range("2026-01-05", periods=30)          # Mon 2026-01-05 …


def panel_for(prices: dict[str, list[float]]) -> Panel:
    close = pd.DataFrame(prices, index=SESSIONS, dtype=float)
    ones = close * 0 + 1
    return Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                 volume=ones, tr=close / close.iloc[0], split_factor=ones)


def snaps(rows):
    frame = pd.DataFrame(rows, columns=["report_date", "security_id", "rank"])
    frame["ticker"] = frame["security_id"]
    frame["report_date"] = pd.to_datetime(frame["report_date"]).dt.date
    return frame


def test_while_listed_exits_at_first_session_of_dropping_report():
    panel = panel_for({"A": [10.0] * 30, "B": [20.0] * 30})
    s = snaps([("2026-01-06", "A", 1), ("2026-01-06", "B", 2), ("2026-01-09", "A", 1)])
    trades = {t.security_id: t for t in while_listed(s, panel, [1, 5], {})}
    assert trades["A"].entry_session == pd.Timestamp("2026-01-06") and trades["A"].exit_session is None
    assert trades["B"].exit_session == pd.Timestamp("2026-01-09")          # report date is a session
    assert trades["B"].exit_signal_date == date(2026, 1, 9)


def test_slot_limits_ranks():
    panel = panel_for({"A": [10.0] * 30, "B": [20.0] * 30})
    s = snaps([("2026-01-06", "A", 1), ("2026-01-06", "B", 6)])
    assert {t.security_id for t in while_listed(s, panel, [1, 5], {})} == {"A"}


def test_fixed_hold_stacks_lots_and_exits_after_n_sessions():
    panel = panel_for({"A": [10.0] * 30})
    s = snaps([("2026-01-06", "A", 1), ("2026-01-09", "A", 1)])
    trades = fixed_hold(s, panel, [1, 2], {"sessions": 5})
    assert len(trades) == 2
    assert trades[0].exit_session == SESSIONS[SESSIONS.get_loc(pd.Timestamp("2026-01-06")) + 5]


def test_price_exit_sells_session_after_close_below_ema_and_blocks_reentry_while_held():
    prices = [10.0] * 25 + [12.0, 12.0, 8.0, 8.0, 8.0]              # dip on session 27
    panel = panel_for({"A": prices})
    s = snaps([("2026-02-09", "A", 1), ("2026-02-10", "A", 1)])
    trades = price_exit(s, panel, "all", {"indicator": "ema", "window": 5, "exit_when": "below"})
    assert len(trades) == 1                                        # second signal arrives while held
    t = trades[0]
    assert t.exit_signal_date == SESSIONS[27].date()
    assert t.exit_session == SESSIONS[28]                          # next session, no look-ahead


def test_nav_equal_weight_rebalance():
    panel = panel_for({"A": [10.0] * 10 + [20.0] * 20, "B": [10.0] * 30})
    s = snaps([("2026-01-05", "A", 1), ("2026-01-05", "B", 2)])
    trades = while_listed(s, panel, [1, 5], {})
    nav = build_nav(trades, panel, panel.tr / (panel.close / panel.close.bfill().iloc[0]), SESSIONS[0])
    # Half in A doubles, half in B flat → 150.
    assert np.isclose(nav["nav_price"].iloc[-1], 150.0)
    assert (nav["positions"] == 2).all()


def test_today_is_final_only_after_the_close():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from market.data.bars import last_final_session_day
    ny = ZoneInfo("America/New_York")
    assert last_final_session_day(datetime(2026, 10, 9, 10, 0, tzinfo=ny)) == date(2026, 10, 8)
    assert last_final_session_day(datetime(2026, 10, 9, 17, 30, tzinfo=ny)) == date(2026, 10, 9)
