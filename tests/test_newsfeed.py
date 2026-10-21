import base64
import json
from types import SimpleNamespace

import pandas as pd

from market.reports.export_newsfeed import holdings, seal
from market.reports.snapshot import upcoming_report


def test_seal_round_trip_and_clear_mode():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    payload = {"reports": [{"date": "2026-10-23", "actions": []}]}
    assert seal(payload, None) == {"encrypted": False, "data": payload}
    box = seal(payload, "s3cret")
    assert box["encrypted"] and "reports" not in json.dumps(box)
    b = lambda s: base64.b64decode(s)                                                     # noqa: E731
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b(box["salt"]), iterations=box["iterations"]).derive(b"s3cret")
    assert json.loads(AESGCM(key).decrypt(b(box["iv"]), b(box["ciphertext"]), None)) == payload


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
