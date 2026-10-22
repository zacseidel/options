"""Strategy families, best variants, feed hysteresis and filter exclusions (docs/PLAN-site.md)."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

import market.categories.catalog  # noqa: F401
from market.categories.families import FAMILIES, VARIANTS
from market.categories.registry import REGISTRY, with_exclusions
from market.evaluate import champions
from market.evaluate.metrics import performance


def test_every_category_has_a_family_and_a_short_name():
    assert set(REGISTRY) == set(VARIANTS)
    for cid, v in VARIANTS.items():
        assert v.family in FAMILIES and v.short
    for f in FAMILIES.values():
        assert f.base is None or VARIANTS[f.base].family == f.id


def test_with_exclusions_keeps_order_and_cuts_after_the_last_kept():
    ranked = pd.DataFrame({"score": [5, 4, 3, 2, 1, 0]}, index=list("ABCDEF"))
    out = with_exclusions(ranked, pd.Series({"B": "crowded", "D": "crowded"}), keep=3)
    assert list(out.index) == list("ABCDE")               # A C E kept; B D skipped in between; F cut
    assert out["excluded"].tolist() == [None, "crowded", None, "crowded", None]
    unfiltered = with_exclusions(ranked, pd.Series(dtype=object), keep=2)
    assert list(unfiltered.index) == ["A", "B"] and unfiltered["excluded"].isna().all()


def test_benchmark_sharpe_matches_the_benchmark_alone():
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(1)
    nav = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 300)), index=idx)
    spy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=idx)
    m = performance(nav, 0.04, spy)
    assert abs(m["benchmark_sharpe"] - performance(spy, 0.04)["sharpe"]) < 1e-6


def test_threshold_handles_negative_spy_sharpe():
    assert abs(champions.threshold(1.0, 1.10) - 1.10) < 1e-12
    assert champions.threshold(-0.5, 1.10) > -0.5             # still means beating SPY


def test_feed_hysteresis(tmp_path):
    from market.store.db import connect
    con = connect(tmp_path / "t.duckdb")
    fam = lambda q_in, q_out: {"x": {"champion": "x.top5", "qualifies_in": q_in, "qualifies_out": q_out}}
    assert champions.update_feed(con, fam(False, True))["x"]["in_feed"] is False   # 1.00–1.10×: not in yet
    assert champions.update_feed(con, fam(True, True))["x"]["in_feed"] is True     # ≥ 1.10×: enters
    assert champions.update_feed(con, fam(False, True))["x"]["in_feed"] is True    # 1.00–1.10×: stays
    assert champions.update_feed(con, fam(False, False))["x"]["in_feed"] is False  # < 1.00×: leaves
    con.close()


def test_champion_needs_the_tie_margin_over_the_base():
    idx = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(7)
    base = pd.Series(100 * np.cumprod(1 + rng.normal(0.0008, 0.01, 400)), index=idx)
    navs = pd.DataFrame({"mom12_sp500.top5": base, "mom12si_sp500.top5": base * 1.0001})   # ~equal Sharpe
    s = lambda sid, cat: SimpleNamespace(id=sid, category=cat, slot=[1, 5], hold="while_listed",
                                         instrument="stock", stage="tracked", params={})
    strategies = [s("mom12_sp500.top5", "mom12_sp500"), s("mom12si_sp500.top5", "mom12si_sp500")]
    out = champions.compute(None, strategies, {}, navs)
    assert out["spy_ldrs"]["champion"] == "mom12_sp500.top5"          # the filter didn't beat it by the margin
