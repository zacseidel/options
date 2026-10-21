import pandas as pd

from market.evaluate.engine import load_strategies
from market.methods.adaptive import IvSignal, branch

METHOD = {"rich": 1.3, "cheap": 0.9}


def test_branch_thresholds():
    assert branch(METHOD, 1.5) == "when_rich"
    assert branch(METHOD, 1.3) == "when_rich"
    assert branch(METHOD, 0.8) == "when_cheap"
    assert branch(METHOD, 1.1) == "otherwise"
    assert branch(METHOD, None) == "otherwise"


def test_signal_reads_the_session_before_entry():
    sig = IvSignal.__new__(IvSignal)
    idx = pd.bdate_range("2026-01-05", periods=3)
    sig.sessions = idx
    sig.ratio = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    sig.pct = sig.ratio.rank(axis=1, pct=True)
    assert sig.at("A", idx[2]) == 2.0
    assert sig.at("A", idx[0]) is None
    assert sig.at("B", idx[2]) is None


def test_adaptive_resolves_sibling_methods(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("""
defaults: {instrument: stock}
strategies:
  - {id: b, category: mom12_sp500, slot: [1, 5], hold: while_listed}
option_methods:
  short_dte: {default: [14, 21]}
  call_dte: {short_dte: [14, 28], short_prefer: 21}
  leap_dte: {12m: {min: 365, max: 600, prefer: 365, roll_below: 180}}
  delta_tol: 0.05
  bases:
    b:
      - {id: csp20, tier: Defensive, instrument: csp, delta: -0.2}
      - {id: leap60h, tier: Balanced, instrument: leap, expiry: 12m, delta: 0.6, sizing: 0.5}
      - {id: leap60f, tier: Aggressive, instrument: leap, expiry: 12m, delta: 0.6, sizing: 1.0}
      - {id: adaptive, tier: Adaptive, instrument: adaptive, rich: 1.3, cheap: 0.9,
         when_rich: csp20, when_cheap: leap60f, otherwise: leap60h, stage: lab, added: 2026-10-21}
""")
    by_id = {s.id: s for s in load_strategies(path)}
    a = by_id["b.adaptive"]
    assert a.instrument == "adaptive" and a.stage == "lab" and by_id["b.csp20"].stage == "tracked"
    assert a.method["branches"]["when_rich"]["instrument"] == "csp"
    assert a.method["branches"]["when_cheap"]["sizing"] == 1.0
    assert "Adaptive" in a.method["label"]
