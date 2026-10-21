"""Earnings announcements from EDGAR: 8-K item 2.02 filings and their acceptance times (PLAN-signals §6).

Companies furnish their results press release on an 8-K with item 2.02, usually minutes after it
goes out, so EDGAR's acceptance time dates the announcement: before 09:30 ET the market reacts that
session, after 16:00 the next one. (Polygon's earnings calendar is a Benzinga add-on, not in the plan.)

Backfill: each tracked company's `submissions` JSON (recent filings), plus older pages back to
FIRST_FILED for companies with very many filings (banks issuing structured notes). Daily: companies
with an 8-K in EDGAR's daily form index are re-read (recent filings only).

Usage:  python -m market.data.earnings [--cik CIK ...]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date, datetime, time as clock, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from market.config import secret
from market.data.fundamentals import tracked_ciks
from market.smartmoney.ingest import DAILY_INDEX
from market.store.db import connect, log_fetch, transaction

SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
SOURCE = "edgar_submissions"
INDEX_SOURCE = "edgar_form_index_8k"
FIRST_FILED = date(2021, 1, 1)
CONCURRENCY = 6
EASTERN = ZoneInfo("America/New_York")
COLUMNS = ["cik", "accn", "filed", "accepted", "items"]


def _to_eastern(utc: datetime) -> datetime:
    return utc.replace(tzinfo=timezone.utc).astimezone(EASTERN).replace(tzinfo=None)


LATE = clock(17, 30)               # EDGAR dates anything accepted after 17:30 ET to the next business day


def _eastern(accepted: str, filed: date) -> datetime:
    """EDGAR's submissions `acceptanceDateTime` as naive US/Eastern.

    The JSON labels it UTC. For many filers it is; for others (Apple, for one) it is the Eastern time
    shifted once more: Apple's 8-K accepted at 16:30:28 ET on 2026-07-30 (per the filing index page)
    reads '2026-07-31T00:30:28.000Z'. Which filers is not knowable from the JSON, but a shifted
    after-close release lands after 17:30 on its own filing date, which can't happen (EDGAR would have
    dated it the next business day), so those are shifted back. A shifted pre-market release (07:00 →
    11:00) stays a few hours late but still reacts in the same session, which is what matters here.
    """
    et = _to_eastern(datetime.fromisoformat(accepted.replace("Z", "")).replace(tzinfo=None))
    if et.date() == filed and et.time() >= LATE:
        et = _to_eastern(et)
    return et


def parse_filings(cik: int, block: dict) -> list[tuple]:
    """2.02 8-Ks in one submissions `recent` block (or an older page)."""
    rows = []
    for form, items, accn, filed, accepted in zip(block["form"], block["items"], block["accessionNumber"],
                                                  block["filingDate"], block["acceptanceDateTime"]):
        if form not in ("8-K", "8-K/A") or "2.02" not in (items or "").split(","):
            continue
        filed_d = date.fromisoformat(filed)
        if filed_d >= FIRST_FILED:
            rows.append((cik, accn, filed_d, _eastern(accepted, filed_d), items))
    return rows


async def _get(client: httpx.AsyncClient, url: str) -> dict | None:
    for attempt in range(4):
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        if resp.status_code in (429, 503) or resp.status_code >= 500:
            await asyncio.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        await asyncio.sleep(0.15)
        return resp.json()
    resp.raise_for_status()
    return None


async def _company(client, limit, cik: int, older: bool) -> tuple[int, list[tuple] | None]:
    async with limit:
        body = await _get(client, SUBMISSIONS.format(name=f"CIK{cik:010d}.json"))
        if body is None:
            return cik, None
        rows = parse_filings(cik, body["filings"]["recent"])
        if older:
            for page in body["filings"].get("files", []):
                if date.fromisoformat(page["filingTo"]) < FIRST_FILED:
                    continue
                more = await _get(client, SUBMISSIONS.format(name=page["name"]))
                if more:
                    rows.extend(parse_filings(cik, more))
        return cik, rows


def fetch(ciks: list[int], older: bool = True) -> dict:
    t0 = time.time()
    con = connect()
    events = 0

    async def run():
        nonlocal events
        headers = {"User-Agent": secret("HTTP_USER_AGENT"), "Accept-Encoding": "gzip, deflate"}
        limit = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=True) as client:
            futures = [_company(client, limit, c, older) for c in ciks]
            for done, future in enumerate(asyncio.as_completed(futures), 1):
                cik, rows = await future
                with transaction(con):
                    if rows:
                        frame = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("accn")
                        con.register("_ev", frame)
                        con.execute(f"INSERT OR REPLACE INTO earnings_events SELECT {', '.join(COLUMNS)} FROM _ev")
                        con.unregister("_ev")
                        events += len(frame)
                    log_fetch(con, SOURCE, str(cik), len(rows or []), immutable=False)
                if done % 200 == 0:
                    print(f"  earnings: {done}/{len(ciks)} companies, {events:,} events", flush=True)

    asyncio.run(run())
    con.close()
    return {"companies": len(ciks), "events": events, "seconds": round(time.time() - t0, 1)}


def eightk_filers(con, today: date, max_days: int = 14) -> tuple[set[int], int]:
    checked = {k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ? AND immutable",
                                         [INDEX_SOURCE]).fetchall()}
    days = [d.date() for d in pd.bdate_range(today - timedelta(days=max_days), today) if str(d.date()) not in checked]
    filers: set[int] = set()
    headers = {"User-Agent": secret("HTTP_USER_AGENT"), "Accept-Encoding": "gzip, deflate"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for day in days:
            q = (day.month - 1) // 3 + 1
            resp = client.get(DAILY_INDEX.format(y=day.year, q=q, d=day.strftime("%Y%m%d")))
            if resp.status_code in (403, 404):
                if day < today - timedelta(days=3):
                    log_fetch(con, INDEX_SOURCE, str(day), 0, immutable=True)
                continue
            resp.raise_for_status()
            found = set()
            for line in resp.text.splitlines():
                if line.startswith("8-K ") or line.startswith("8-K/A "):
                    parts = line.rsplit(None, 3)
                    if len(parts) == 4 and parts[1].isdigit():
                        found.add(int(parts[1]))
            filers |= found
            log_fetch(con, INDEX_SOURCE, str(day), len(found), immutable=day < today)
            time.sleep(0.15)
    return filers, len(days)


def sync(today: date | None = None) -> dict:
    """Daily: backfill companies never read (with older pages), then re-read the day's 8-K filers."""
    today = today or date.today()
    con = connect()
    tracked = tracked_ciks(con)
    seen = {int(k) for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ?", [SOURCE]).fetchall()}
    if not seen:
        for d in pd.bdate_range(today - timedelta(days=14), today - timedelta(days=1)):
            log_fetch(con, INDEX_SOURCE, str(d.date()), 0, immutable=True)
    filers, days = eightk_filers(con, today)
    con.close()
    new = sorted(c for c in tracked if c not in seen)
    out = {"index_days": days}
    if new:
        out["backfill"] = fetch(new, older=True)
    recent = sorted((filers & set(tracked)) - set(new))
    if recent:
        out["recent"] = fetch(recent, older=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cik", type=int, nargs="+")
    args = parser.parse_args()
    print(fetch(args.cik) if args.cik else sync())


if __name__ == "__main__":
    main()
