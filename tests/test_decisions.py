"""Decisions page: positions.md parsing, lot pricing against the SPY shadow, per-ticker consolidation."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd

from market.reports.export_decisions import consolidate, first_needed, parse_bullet, parse_positions, price_lot

TEXT = """
# header text is ignored
## Growth
### Open
- nvda | 2025-01-02 | 5 | AI
- NVDA | 01/06/2025 | 3
- AAPL |  | 10
- MSFT | 2025-01-02 | notes without shares
### Closed
- TSLA | 2025-01-02 | 2025-01-08 | 4 | trimmed
## Growth
### Open
- BRKB | 2025-01-03 | 1
## Archive
- META | 2025-01-02 | 2025-01-07 | 2 | done
- KO | 2025-01-02 | 1
"""


def test_parse_positions_shares_dates_merge_and_archive():
    buckets = parse_positions(TEXT)
    assert [b.name for b in buckets] == ["Growth", "Archive"]          # same-named buckets merge
    growth, archive = buckets
    by = [(l.ticker, l.open_date, l.close_date, l.shares, l.shares_given) for l in growth.lots]
    assert by[0] == ("NVDA", date(2025, 1, 2), None, 5.0, True)
    assert by[1][1] == date(2025, 1, 6) and by[1][3] == 3.0             # MM/DD/YYYY
    assert by[2] == ("AAPL", None, None, 10.0, True)                    # undated open lot
    assert by[3][3] == 10.0 and by[3][4] is False                       # no share count → default
    assert growth.lots[3].notes == "notes without shares"
    assert by[4] == ("TSLA", date(2025, 1, 2), date(2025, 1, 8), 4.0, True)
    assert growth.lots[-1].ticker == "BRK.B"                            # alias
    assert archive.archived and [l.closed for l in archive.lots] == [True, False]   # dates decide


def test_closed_lot_needs_both_dates():
    assert parse_bullet("- TSLA | 2025-01-02 | 4", "closed") is None
    assert parse_bullet("- 123 | 2025-01-02", "open") is None


def _panel():
    days = pd.bdate_range("2025-01-01", periods=10)
    stock_tr = pd.Series(np.linspace(100, 150, 10), index=days)       # +50% over the window
    spy_tr = pd.Series(np.linspace(100, 110, 10), index=days)         # +10%
    raw = stock_tr * 2                                                 # traded price differs from the TR index
    panel = SimpleNamespace(tr=pd.DataFrame({"X": stock_tr, "SPY": spy_tr}), raw_close=pd.DataFrame({"X": raw}),
                            sessions=days)
    return panel, spy_tr, days


def test_price_lot_against_the_spy_shadow():
    panel, spy_tr, days = _panel()
    lot = parse_bullet("- X | 2025-01-01 | 10", "open")
    r = price_lot(lot, "X", panel, spy_tr)
    assert r["cost"] == 10 * 200.0                                      # shares × the close it was bought at
    assert abs(r["ret"] - 0.5) < 1e-9 and abs(r["spy_ret"] - 0.1) < 1e-9 and abs(r["alpha"] - 0.4) < 1e-9
    assert abs(r["spy_value"] - 2000 * 1.1) < 1e-6
    assert price_lot(lot, None, panel, spy_tr)["priced"] is False


def test_consolidation_is_dollar_weighted():
    panel, spy_tr, days = _panel()
    a = price_lot(parse_bullet("- X | 2025-01-01 | 10", "open"), "X", panel, spy_tr)    # cost 2000, +50%
    b = price_lot(parse_bullet(f"- X | {days[5].date()} | 30", "open"), "X", panel, spy_tr)   # bought higher
    row = consolidate([a, b])[0]
    assert row["n"] == 2 and row["shares"] == 40
    cost = a["cost"] + b["cost"]
    assert abs(row["ret"] - ((a["value"] + b["value"]) / cost - 1)) < 1e-9
    assert abs(row["alpha"] - ((a["value"] + b["value"] - a["spy_value"] - b["spy_value"]) / cost)) < 1e-9
    assert row["beat"] == 2 and len(row["lots"]) == 2


def test_first_needed_reaches_back_before_the_earliest_buy():
    need = first_needed(parse_positions(TEXT), history_start=date(2021, 10, 1))
    assert need["NVDA"] == date(2024, 12, 23) and need["AAPL"] == date(2021, 10, 1)


def test_xirr_matches_a_known_rate():
    from market.reports.export_decisions import xirr
    t0 = pd.Timestamp("2024-01-01")
    flows = [(t0, -1000.0), (t0 + pd.Timedelta(days=731), 1000 * 1.10 ** (731 / 365.25))]   # 10% a year
    assert abs(xirr(flows) - 0.10) < 1e-6
    assert xirr([(t0, -1000.0)]) is None


def test_annualized_is_the_yearly_gap_whatever_the_holding_periods():
    from market.reports.export_decisions import annualized
    t0 = pd.Timestamp("2023-01-02")

    def lot(cost, days):                       # earns 10% a year while SPY earns 5%, for `days`
        years = days / 365.25
        return {"priced": True, "cost": cost, "value": cost * 1.10 ** years, "spy_value": cost * 1.05 ** years,
                "_entry": t0, "_end": t0 + pd.Timedelta(days=days)}
    a = annualized([lot(1000, 1096), lot(9000, 365)])
    assert abs(a["ann"] - 0.10) < 1e-4 and abs(a["spy_ann"] - 0.05) < 1e-4 and abs(a["ann_alpha"] - 0.05) < 1e-4
    assert "ann" not in annualized([lot(9000, 30)])    # under three months: too short to annualize


def test_undated_lot_is_graded_over_the_last_two_years():
    days = pd.bdate_range("2021-01-04", "2026-10-21")
    tr = pd.Series(np.linspace(100, 200, len(days)), index=days)
    panel = SimpleNamespace(tr=pd.DataFrame({"X": tr, "SPY": tr}), raw_close=pd.DataFrame({"X": tr}), sessions=days)
    r = price_lot(parse_bullet("- X |  | 10", "open"), "X", panel, tr)
    assert r["assumed"] and r["entry_date"] == "2024-10-21"
