"""EDGAR XBRL fundamentals: companyfacts → `fundamental_facts` (PLAN-signals §5).

One `companyfacts` file per company (~270 KB gzipped), parsed in memory and discarded; only the
metrics in CONCEPTS are kept, for periods ending FIRST_PERIOD_END or later, with every filing
that reported them (so a value can be used from the day it was first filed). Polygon's financials
are not in the Starter plan; EDGAR is free and carries the filing date of each fact.

Daily: EDGAR's daily form index lists the day's 10-K / 10-Q filers; only those companies are
re-fetched. Backfill: every tracked company without stored facts.

Usage:  python -m market.data.fundamentals [--cik CIK ...] [--refresh-all]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date, timedelta

import httpx
import pandas as pd

from market.config import secret
from market.smartmoney.ingest import DAILY_INDEX
from market.store.db import connect, log_fetch, transaction

COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SOURCE = "edgar_companyfacts"
INDEX_SOURCE = "edgar_form_index_10q"
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT"}
FIRST_PERIOD_END = date(2015, 1, 1)
CONCURRENCY = 6                   # SEC's limit is 10 requests a second

# metric → XBRL tags in priority order ("dei:" for cover-page facts). For each period the first tag
# that reports it wins, which handles the 2018 move from SalesRevenueNet to the ASC 606 tags.
CONCEPTS: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
                "RevenuesNetOfInterestExpense"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_out": ["dei:EntityCommonStockSharesOutstanding"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets": ["Assets"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
}
UNITS = {"diluted_shares": "shares", "shares_out": "shares"}
FACT_COLUMNS = ["cik", "metric", "concept", "priority", "start", "end", "value", "form", "filed", "accn"]


def parse_companyfacts(cik: int, payload: dict) -> pd.DataFrame:
    """The CONCEPTS facts of one companyfacts payload as FACT_COLUMNS rows."""
    facts = payload.get("facts", {})
    rows = []
    for metric, tags in CONCEPTS.items():
        unit = UNITS.get(metric, "USD")
        for priority, tag in enumerate(tags):
            taxonomy, name = tag.split(":") if ":" in tag else ("us-gaap", tag)
            for f in facts.get(taxonomy, {}).get(name, {}).get("units", {}).get(unit, []):
                if f.get("form") not in FORMS or f.get("val") is None or not f.get("filed"):
                    continue
                end = date.fromisoformat(f["end"])
                if end < FIRST_PERIOD_END:
                    continue
                start = date.fromisoformat(f["start"]) if f.get("start") else None
                rows.append((cik, metric, name, priority, start, end, float(f["val"]), f["form"],
                             date.fromisoformat(f["filed"]), f.get("accn", "")))
    frame = pd.DataFrame(rows, columns=FACT_COLUMNS)
    return frame.drop_duplicates(["metric", "concept", "start", "end", "accn"])


def tracked_ciks(con) -> list[int]:
    rows = con.execute("SELECT DISTINCT cik FROM securities WHERE cik IS NOT NULL AND type IN ('CS', 'ADRC')").fetchall()
    return sorted({int(c) for (c,) in rows if str(c).isdigit()})


async def _fetch(client: httpx.AsyncClient, limit: asyncio.Semaphore, cik: int) -> tuple[int, dict | None]:
    async with limit:
        for attempt in range(4):
            resp = await client.get(COMPANYFACTS.format(cik=cik))
            if resp.status_code == 404:
                return cik, None                  # no XBRL filings (e.g. a foreign filer on 20-F/40-F)
            if resp.status_code in (429, 503) or resp.status_code >= 500:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            await asyncio.sleep(0.15)             # stay under SEC's rate limit
            return cik, resp.json()
        resp.raise_for_status()
        return cik, None


async def _fetch_all(ciks: list[int]):
    headers = {"User-Agent": secret("HTTP_USER_AGENT"), "Accept-Encoding": "gzip, deflate"}
    limit = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=True) as client:
        for future in asyncio.as_completed([_fetch(client, limit, c) for c in ciks]):
            yield await future


def store(con, cik: int, frame: pd.DataFrame) -> None:
    with transaction(con):
        con.execute("DELETE FROM fundamental_facts WHERE cik = ?", [cik])
        if not frame.empty:
            con.register("_facts", frame)
            columns = ", ".join(f'"{c}"' for c in FACT_COLUMNS)
            con.execute(f"INSERT INTO fundamental_facts ({columns}) SELECT {columns} FROM _facts")
            con.unregister("_facts")
        log_fetch(con, SOURCE, str(cik), len(frame), immutable=False)


def fetch(ciks: list[int]) -> dict:
    """(Re)load companyfacts for these companies."""
    t0 = time.time()
    con = connect()
    rows = missing = 0

    async def run():
        nonlocal rows, missing
        done = 0
        async for cik, payload in _fetch_all(ciks):
            done += 1
            if payload is None:
                missing += 1
                log_fetch(con, SOURCE, str(cik), 0, immutable=False)
                continue
            frame = parse_companyfacts(cik, payload)
            store(con, cik, frame)
            rows += len(frame)
            if done % 100 == 0:
                print(f"  fundamentals: {done}/{len(ciks)} companies, {rows:,} facts", flush=True)

    asyncio.run(run())
    con.close()
    return {"companies": len(ciks), "no_xbrl": missing, "facts": rows, "seconds": round(time.time() - t0, 1)}


def parse_periodic_index(text: str) -> set[int]:
    """CIKs with a 10-K / 10-Q (or amendment) in an EDGAR daily form index."""
    out = set()
    for line in text.splitlines():
        form = line.split(None, 1)[0] if line.strip() else ""
        if form not in FORMS:
            continue
        try:
            _, cik, _, _ = line.rsplit(None, 3)
        except ValueError:
            continue
        if cik.isdigit():
            out.add(int(cik))
    return out


def new_filers(con, today: date, max_days: int = 14) -> tuple[set[int], int]:
    """Tracked companies with a periodic filing on a daily-index day not yet checked."""
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
                if day < today - timedelta(days=3):          # long past and absent: a holiday
                    log_fetch(con, INDEX_SOURCE, str(day), 0, immutable=True)
                continue
            resp.raise_for_status()
            found = parse_periodic_index(resp.text)
            filers |= found
            log_fetch(con, INDEX_SOURCE, str(day), len(found), immutable=day < today)
            time.sleep(0.15)
    return filers, len(days)


def sync(today: date | None = None) -> dict:
    """Daily: backfill companies never fetched, then re-fetch the day's 10-K / 10-Q filers we track."""
    today = today or date.today()
    con = connect()
    tracked = tracked_ciks(con)
    fetched = {int(k) for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ?", [SOURCE]).fetchall()}
    if not fetched:
        # First run: mark the recent index days as seen; the backfill below covers them.
        for d in pd.bdate_range(today - timedelta(days=14), today - timedelta(days=1)):
            log_fetch(con, INDEX_SOURCE, str(d.date()), 0, immutable=True)
    filers, days = new_filers(con, today)
    con.close()
    todo = sorted(set(c for c in tracked if c not in fetched) | (filers & set(tracked)))
    stats = fetch(todo) if todo else {"companies": 0}
    return {**stats, "index_days": days, "filers_tracked": len(filers & set(tracked))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cik", type=int, nargs="+")
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()
    if args.cik or args.refresh_all:
        con = connect()
        ciks = args.cik or tracked_ciks(con)
        con.close()
        print(fetch(ciks))
    else:
        print(sync())


if __name__ == "__main__":
    main()
