"""Daily disclosure check: new Congress PTRs and new 13F filings, written to smartmoney's ledgers.

Until the fetchers are ported (decision D3), smartmoney's own modules do the fetching, run in
its interpreter and directory, so its weekly job and this check maintain one ledger:

  Congress  House Clerk index + Senate eFD search for the trailing window (only unseen
            filings are downloaded). Paper filings (OCR) stay with smartmoney's weekly run.
  13F       EDGAR's daily form index for each business day since the last check (one small
            request per day) → the funds already in the ledger that filed → fetch just those.

Skipped while smartmoney's own update is running, so the two never write the ledger at once.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta

import httpx
import pandas as pd

from market.config import config, path, secret
from market.smartmoney import ledgers
from market.store.db import connect, log_fetch

SMARTMONEY_PYTHON = "/Users/zacseidel/opt/anaconda3/bin/python3"
DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{d}.idx"
LOOKBACK_DAYS = 730
EDGAR_SOURCE = "edgar_daily_13f"


def _smartmoney_busy() -> bool:
    out = subprocess.run(["pgrep", "-f", "smartmoney/src/(update|refresh_all|backfill)"],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def _python() -> str:
    return (config().get("smartmoney") or {}).get("python") or SMARTMONEY_PYTHON


def _run_smartmoney(code: str, timeout: int) -> dict:
    root = path("smartmoney_repo")
    env = {**os.environ, "PYTHONPATH": f"{root / 'src'}:{root / 'src' / 'hedge'}"}
    proc = subprocess.run([_python(), "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
    if proc.returncode != 0:
        raise RuntimeError(f"smartmoney fetch failed: {' | '.join(tail)}")
    return {"log": tail}


def congress() -> dict:
    before = len(ledgers.congress_transactions())
    result = _run_smartmoney(
        f"import fetch_house, fetch_senate; fetch_house.run({LOOKBACK_DAYS}); fetch_senate.run({LOOKBACK_DAYS})",
        timeout=1800)
    ledgers.clear_cache()
    return {"transactions": len(ledgers.congress_transactions()), "new": len(ledgers.congress_transactions()) - before,
            **result}


def parse_form_idx(text: str) -> list[tuple[str, int, str]]:
    """13F-HR / 13F-HR/A rows of an EDGAR form index → (form, cik, filed)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("13F-HR"):        # 13F-NT notices carry no holdings
            continue
        try:
            left, cik, filed, _ = line.rsplit(None, 3)
        except ValueError:
            continue
        if cik.isdigit():
            rows.append((left.split(None, 1)[0], int(cik), filed))
    return rows


def _daily_index(client: httpx.Client, day: date) -> list[tuple[str, int, str]] | None:
    q = (day.month - 1) // 3 + 1
    resp = client.get(DAILY_INDEX.format(y=day.year, q=q, d=day.strftime("%Y%m%d")))
    if resp.status_code in (403, 404):
        return None                              # not published (yet) or a holiday
    resp.raise_for_status()
    return parse_form_idx(resp.text)


def new_13f_filers(today: date | None = None, max_days: int = 21) -> tuple[set[int], dict]:
    """Funds in the ledger that filed a 13F on a day not yet checked."""
    today = today or date.today()
    con = connect()
    checked = {k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ? AND immutable",
                                         [EDGAR_SOURCE]).fetchall()}
    days = [d.date() for d in pd.bdate_range(today - timedelta(days=max_days), today) if str(d.date()) not in checked]
    _, _, managers = ledgers.holdings()
    known = {int(c) for c in managers}
    filers: set[int] = set()
    seen = 0
    headers = {"User-Agent": secret("HTTP_USER_AGENT"), "Accept-Encoding": "gzip, deflate"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for day in days:
            rows = _daily_index(client, day)
            if rows is None:
                if day < today - timedelta(days=3):      # long past and absent: a holiday
                    log_fetch(con, EDGAR_SOURCE, str(day), 0, immutable=True)
                continue
            seen += len(rows)
            filers |= {cik for _, cik, _ in rows if cik in known}
            log_fetch(con, EDGAR_SOURCE, str(day), len(rows), immutable=day < today)
    con.close()
    return filers, {"days_checked": len(days), "filings_seen": seen, "ledger_funds_filed": len(filers)}


def hedge(today: date | None = None) -> dict:
    filers, stats = new_13f_filers(today)
    if filers:
        ciks = sorted(filers)
        _run_smartmoney(
            f"import fetch_13f, resolve_cusip; fetch_13f.run({ciks}, lookback_days={LOOKBACK_DAYS}); "
            f"resolve_cusip.run(ciks=set({ciks}))", timeout=3600)
        ledgers.clear_cache()
    return stats


def run() -> dict:
    if _smartmoney_busy():
        return {"skipped": "smartmoney's own update is running"}
    out = {}
    for name, fn in (("congress", congress), ("hedge", hedge)):
        try:
            out[name] = fn()
        except Exception as exc:                 # one source failing shouldn't block the other
            out[name] = {"error": repr(exc)[:300]}
    return out
