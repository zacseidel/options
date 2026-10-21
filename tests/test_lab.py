from datetime import date

import numpy as np
import pandas as pd
import pytest

from market.categories.registry import Context, Sources, source, SOURCE_LOADERS
from market.evaluate.engine import load_strategies, window_slices
from market.research.common import bucket_table, forward_excess, split
from market.research.lead_time import entries, lead_stats
from market.store.panel import Panel


def test_strategy_stage_and_added(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("""
defaults: {instrument: stock}
strategies:
  - {id: a, category: mom12_sp500, slot: [1, 5], hold: while_listed}
  - {id: b, category: mom12_sp500, slot: [1, 5], hold: while_listed, stage: lab, added: 2026-10-21}
option_methods:
  short_dte: {default: [14, 21]}
  call_dte: {short_dte: [14, 28], short_prefer: 21}
  leap_dte: {12m: {min: 365, max: 600, prefer: 365, roll_below: 180}}
  delta_tol: 0.05
  bases:
    b:
      - {id: csp20, tier: Defensive, instrument: csp, delta: -0.2}
""")
    by_id = {s.id: s for s in load_strategies(path)}
    assert by_id["a"].stage == "tracked" and by_id["a"].added is None
    assert by_id["b"].stage == "lab" and by_id["b"].added == date(2026, 10, 21)
    assert by_id["b.csp20"].stage == "lab" and by_id["b.csp20"].added == date(2026, 10, 21)   # inherits its base


def test_bad_stage_rejected(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("strategies:\n  - {id: a, category: x, slot: all, hold: while_listed, instrument: stock, stage: trial}\n")
    with pytest.raises(ValueError):
        load_strategies(path)


def test_since_added_window():
    nav = pd.Series(np.linspace(100, 120, 30), index=pd.bdate_range("2026-01-05", periods=30))
    parts = window_slices(nav, {"all": None}, date(2026, 2, 2))
    assert parts["since_added"].index[0] == pd.Timestamp("2026-02-02")
    assert "since_added" not in window_slices(nav, {"all": None}, date(2027, 1, 1))
    assert "since_added" not in window_slices(nav, {"all": None})


def test_sources_are_lazy_and_built_once():
    calls = []

    @source("_test_source")
    def _load(con, panel):
        calls.append(1)
        return {"x": 1}

    try:
        sources = Sources(None, None)
        ctx = Context(report_date=date(2026, 1, 6), panel=None, membership=None, caps=None, securities=None,
                      dollar_volume=None, sources=sources)
        assert calls == []
        assert ctx.source("_test_source") == {"x": 1}
        ctx2 = Context(report_date=date(2026, 1, 9), panel=None, membership=None, caps=None, securities=None,
                       dollar_volume=None, sources=sources)
        ctx2.source("_test_source")
        assert calls == [1]
        with pytest.raises(KeyError):
            ctx.source("missing")
    finally:
        SOURCE_LOADERS.pop("_test_source")


def _panel(values: dict[str, list[float]]) -> Panel:
    idx = pd.bdate_range("2026-01-05", periods=len(next(iter(values.values()))))
    close = pd.DataFrame(values, index=idx, dtype=float)
    ones = close * 0 + 1
    return Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close,
                 volume=ones, tr=close, split_factor=ones)


def test_forward_excess_starts_the_session_after_the_event():
    panel = _panel({"A": [10, 10, 11, 12, 13, 14], "SPY": [100, 100, 100, 101, 102, 103]})
    events = pd.DataFrame({"security_id": ["A", "A"], "date": [date(2026, 1, 5), date(2026, 1, 9)]})
    out = forward_excess(panel, events, "SPY", horizons=(2,))
    # event on Mon 01-05 → enter Tue (10), two sessions later Thu (12): +20%; SPY 100 → 101
    assert out.loc[0, "ret_2"] == pytest.approx(0.20)
    assert out.loc[0, "xs_2"] == pytest.approx(0.20 - 0.01)
    assert np.isnan(out.loc[1, "ret_2"])          # runs past the end of history


def test_split_and_buckets():
    frame = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=100), "f": range(100), "r": np.arange(100) / 100})
    before, after = split(frame, date(2025, 3, 1))
    assert len(before) + len(after) == 100 and pd.to_datetime(after["date"]).min() >= pd.Timestamp("2025-03-01")
    table = bucket_table(frame, "f", "r", buckets=5)
    assert list(table["bucket"]) == [1, 2, 3, 4, 5] and table["mean"].is_monotonic_increasing


def test_lead_time_counts_only_names_not_already_leading():
    d = pd.to_datetime
    top = pd.DataFrame({
        "category_id": ["c", "c", "c", "L", "L"],
        "report_date": d(["2025-01-07", "2025-01-07", "2025-01-10", "2025-01-03", "2025-03-04"]),
        "security_id": ["x", "y", "z", "y", "x"],
    })
    top = pd.concat([top, pd.DataFrame({"category_id": ["L"], "report_date": d(["2026-06-01"]), "security_id": ["q"]})])
    ent = entries(top, "c")
    assert sorted(ent["security_id"]) == ["x", "y", "z"]        # z enters on 01-10; x, y on 01-07, x/y leave then
    stats = lead_stats(ent, top[top["category_id"] == "L"])
    assert stats["entries"] == 3
    assert stats["already_leader"] == pytest.approx(1 / 3, abs=1e-4)    # y led 4 days before entering
    assert stats["became_leader"] == pytest.approx(1 / 3, abs=1e-4)     # x leads 56 days later
    assert stats["median_lead_days"] == 56


def test_ranks_12m_uses_members_on_the_day():
    from market.categories.steady import Ranks12m
    idx = pd.bdate_range("2025-01-01", periods=260)
    close = pd.DataFrame({"A": np.linspace(10, 30, 260), "B": np.linspace(10, 20, 260), "C": np.linspace(10, 40, 260)},
                         index=idx)
    ones = close * 0 + 1
    panel = Panel(close=close, open=close, high=close, low=close, vwap=close, raw_close=close, volume=ones, tr=close,
                  split_factor=ones)
    r = Ranks12m.__new__(Ranks12m)
    r.members = pd.DataFrame({"universe": ["sp500"] * 3, "security_id": ["A", "B", "C"],
                              "valid_from": [pd.Timestamp.min] * 3,
                              "valid_to": [pd.Timestamp.max, pd.Timestamp.max, idx[255]]})
    r.panel, r._memo, r.ret = panel, {}, close / close.shift(252) - 1
    assert r.rank("sp500", idx[254]).to_dict() == {"A": 2.0, "B": 3.0, "C": 1.0}
    assert r.rank("sp500", idx[259]).to_dict() == {"A": 1.0, "B": 2.0}       # C left the index
