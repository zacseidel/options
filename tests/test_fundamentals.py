from datetime import date

import pandas as pd
import pytest

from market.data.fundamental_metrics import quarterly, states
from market.data.fundamentals import parse_companyfacts, parse_periodic_index

D = date.fromisoformat


def _fact(metric, start, end, value, filed, priority=0, concept="X", form="10-Q"):
    return {"cik": 1, "metric": metric, "concept": concept, "priority": priority,
            "start": D(start) if start else None, "end": D(end), "value": value, "form": form,
            "filed": D(filed), "accn": f"{filed}-{metric}"}


def _year(fy: int, revenue: list[float], filed_q: list[str], filed_k: str, cash_ytd: bool = True):
    """One fiscal year (calendar quarters): 10-Q revenue for Q1-Q3, FY revenue in the 10-K."""
    s, rows = f"{fy}-01-01", []
    ends = [f"{fy}-03-31", f"{fy}-06-30", f"{fy}-09-30"]
    starts = [f"{fy}-01-01", f"{fy}-04-01", f"{fy}-07-01"]
    for i in range(3):
        rows.append(_fact("revenue", starts[i], ends[i], revenue[i], filed_q[i]))
        rows.append(_fact("net_income", starts[i], ends[i], revenue[i] / 10, filed_q[i]))
        rows.append(_fact("diluted_shares", starts[i], ends[i], 100.0, filed_q[i]))
        rows.append(_fact("ocf", s, ends[i], sum(revenue[: i + 1]) / 5, filed_q[i]))     # year-to-date
    rows.append(_fact("revenue", s, f"{fy}-12-31", sum(revenue), filed_k, form="10-K"))
    rows.append(_fact("net_income", s, f"{fy}-12-31", sum(revenue) / 10, filed_k, form="10-K"))
    rows.append(_fact("diluted_shares", s, f"{fy}-12-31", 100.0, filed_k, form="10-K"))
    rows.append(_fact("ocf", s, f"{fy}-12-31", sum(revenue) / 5, filed_k, form="10-K"))
    return rows


def _facts():
    rows = []
    rows += _year(2023, [100, 110, 120, 130], ["2023-05-01", "2023-08-01", "2023-11-01"], "2024-02-15")
    rows += _year(2024, [120, 135, 150, 170], ["2024-05-01", "2024-08-01", "2024-11-01"], "2025-02-15")
    rows += _year(2025, [150, 175, 200, 230], ["2025-05-01", "2025-08-01", "2025-11-01"], "2026-02-15")
    # The 2024 10-K restates Q3-2023 revenue (comparative): first-filed value must win.
    rows.append(_fact("revenue", "2023-07-01", "2023-09-30", 999, "2024-11-01"))
    # A lower-priority tag for the same period is ignored.
    rows.append(_fact("revenue", "2024-01-01", "2024-03-31", 5, "2024-05-01", priority=2, concept="SalesRevenueNet"))
    return pd.DataFrame(rows)


def test_quarters_from_ytd_and_annual_facts():
    q = quarterly(_facts()).set_index("end")
    assert len(q) == 12
    assert q.loc[pd.Timestamp("2023-09-30"), "revenue"] == 120                  # first filed, not the restatement
    assert q.loc[pd.Timestamp("2023-12-31"), "revenue"] == pytest.approx(130)   # Q4 = FY − 9M
    assert q.loc[pd.Timestamp("2023-12-31"), "filed"] == pd.Timestamp("2024-02-15")
    assert q.loc[pd.Timestamp("2024-06-30"), "ocf"] == pytest.approx(135 / 5)   # 6M YTD − 3M
    assert q.loc[pd.Timestamp("2024-03-31"), "revenue"] == 120                  # preferred tag wins


def test_states_growth_acceleration_and_timing():
    st = states(quarterly(_facts())).set_index("end")
    q4 = st.loc[pd.Timestamp("2025-12-31")]
    assert q4["effective"] == pd.Timestamp("2026-02-16")                        # usable the day after filing
    assert q4["revenue_ttm"] == pytest.approx(150 + 175 + 200 + 230)
    assert q4["rev_yoy_q"] == pytest.approx(230 / 170 - 1)
    q3 = st.loc[pd.Timestamp("2025-09-30")]
    assert q4["rev_accel"] == pytest.approx((230 / 170 - 1) - (200 / 150 - 1))
    assert q3["rev_ttm_yoy"] == pytest.approx((170 + 150 + 175 + 200) / (130 + 120 + 135 + 150) - 1)
    assert q4["shares_yoy"] == pytest.approx(0.0)
    assert st["revenue_ttm"].isna().sum() == 3                                  # first three quarters lack a TTM


def test_parse_companyfacts_keeps_forms_and_recent_periods():
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2024-01-01", "end": "2024-03-31", "val": 10, "form": "10-Q", "filed": "2024-05-01", "accn": "a"},
        {"start": "2024-01-01", "end": "2024-03-31", "val": 10, "form": "8-K", "filed": "2024-04-20", "accn": "b"},
        {"start": "2013-01-01", "end": "2013-03-31", "val": 7, "form": "10-Q", "filed": "2013-05-01", "accn": "c"},
    ]}}}, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2024-04-25", "val": 1000, "form": "10-Q", "filed": "2024-05-01", "accn": "a"}]}}}}}
    frame = parse_companyfacts(7, payload)
    assert set(frame["metric"]) == {"revenue", "shares_out"}
    assert len(frame[frame["metric"] == "revenue"]) == 1


def test_periodic_index_parsing():
    text = ("Form Type   Company Name   CIK   Date Filed   File Name\n"
            "10-Q        APPLE INC      320193   20260731   edgar/data/320193/x.txt\n"
            "8-K         APPLE INC      320193   20260731   edgar/data/320193/y.txt\n"
            "10-K/A      SOME CO        12345    20260731   edgar/data/12345/z.txt\n")
    assert parse_periodic_index(text) == {320193, 12345}
