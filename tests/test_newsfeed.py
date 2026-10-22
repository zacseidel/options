import base64
import json
from types import SimpleNamespace

import pandas as pd

from market.reports.export_newsfeed import holdings
from market.reports.snapshot import upcoming_report


def test_site_lock_round_trip_and_manifest():
    import base64

    from market.reports.site_lock import CHECK, Lock
    lock = Lock("s3cret phrase", iterations=1000)
    text = json.dumps({"reports": [{"date": "2026-10-23"}]})
    sealed = lock.seal_text(text)
    assert "reports" not in sealed and json.loads(sealed)["v"] == 1
    assert lock.open_text(sealed) == text
    m = lock.manifest()
    other = Lock("s3cret phrase", salt=base64.b64decode(m["salt"]), iterations=m["iterations"])
    assert other._aead.decrypt(base64.b64decode(m["check"]["iv"]), base64.b64decode(m["check"]["ct"]), None) == CHECK


def _snaps(rows):
    f = pd.DataFrame(rows, columns=["report_date", "security_id", "rank"])
    f["report_date"] = pd.to_datetime(f["report_date"])
    f["features"] = [{}] * len(f)
    return f


def test_holdings_while_listed_and_fixed_hold():
    sessions = pd.bdate_range("2026-10-01", "2026-10-30")
    snaps = _snaps([("2026-10-06", "A", 1), ("2026-10-06", "B", 2), ("2026-10-06", "C", 7),
                    ("2026-10-09", "A", 1), ("2026-10-13", "B", 1)])
    wl = SimpleNamespace(slot=[1, 5], hold="while_listed", params={})
    h = holdings(wl, snaps, pd.Timestamp("2026-10-06"), sessions)
    assert set(h) == {"A", "B"} and h["A"]["weight"] == 0.5
    fixed = SimpleNamespace(slot="all", hold="fixed_hold", params={"sessions": 4})
    h = holdings(fixed, snaps, pd.Timestamp("2026-10-09"), sessions)
    # Lots from 10-06 (entered 10-06, held 4 sessions: through 10-09) and 10-09 are open on 10-09.
    assert h["A"]["lots"] == 2 and set(h) == {"A", "B", "C"}
    h = holdings(fixed, snaps, pd.Timestamp("2026-10-13"), sessions)
    assert set(h) == {"A", "B"} and h["B"]["weight"] == 0.5          # the 10-06 lots have ended


def test_upcoming_report_is_the_next_session_when_it_is_a_report_day():
    for last, expected in (("2026-10-19", "2026-10-20"), ("2026-10-22", "2026-10-23"), ("2026-10-20", None)):
        panel = SimpleNamespace(sessions=pd.bdate_range("2026-10-01", last))
        got = upcoming_report(panel)
        assert (str(got) if got else None) == expected


def test_allocation_lowest_kelly_scaling_cap_and_spy():
    from market.reports.export_newsfeed import allocate
    kelly = {"A": 0.20, "B": 0.10}
    # Under 100%: sizes as they are, the rest in SPY; a stock on both lists takes the lower half-Kelly.
    w, info = allocate({"x": ["A"], "y": ["A", "B"]}, kelly, cap=0.30)
    assert w == {"x": 0.20, "y": 0.10} and abs(info["spy"] - 0.70) < 1e-9 and info["scale"] == 1.0
    # Over 100%: scaled proportionally to fit, nothing left for SPY.
    held = {f"s{i}": ["A"] for i in range(8)}                       # 8 × 20% = 160%
    w, info = allocate(held, kelly, cap=0.30)
    assert abs(sum(w.values()) - 1.0) < 1e-9 and abs(info["scale"] - 1 / 1.6) < 1e-9 and info["spy"] < 1e-9
    # The cap binds: one stock alone at 20% stays 20%; with a 15% cap it is cut and the rest goes to SPY.
    w, info = allocate({"x": ["A"]}, kelly, cap=0.15)
    assert w == {"x": 0.15} and abs(info["spy"] - 0.85) < 1e-9 and "x" in info["capped"]
