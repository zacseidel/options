"""Insider purchases: open-market buys reported on Form 4 (PLAN-signals §7).

Only non-derivative transactions with code P (open-market or private purchase) and acquired 'A' are
kept: grants, option exercises, gifts and sales are noise for this purpose (zacseidel/insiders' rule).

  * History: the SEC's quarterly insider-transactions data sets (all issuers, ~15 MB a quarter,
    streamed and discarded) from FIRST_QUARTER on.
  * Days after the latest published quarter: EDGAR's daily form index → Form 4s that name a company we
    track → the filing's XML. When the SEC publishes that quarter's data set, it replaces those rows.

Usage:  python -m market.data.insiders
"""

from __future__ import annotations

import argparse
import io
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import httpx
import pandas as pd

from market.config import secret
from market.data.fundamentals import tracked_ciks
from market.smartmoney.ingest import DAILY_INDEX
from market.store.db import connect, log_fetch, transaction

DATASET = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
ARCHIVE = "https://www.sec.gov/Archives/{path}"
DATASET_SOURCE = "sec_form345_dataset"
DAY_SOURCE = "edgar_form4_day"
FIRST_QUARTER = (2021, 1)
WORKERS = 4
COLUMNS = ["accn", "seq", "issuer_cik", "issuer_name", "ticker", "owner_cik", "owner_name", "is_director",
           "is_officer", "is_ten_pct", "officer_title", "trans_date", "filed", "shares", "price", "value",
           "shares_after", "direct", "plan_10b5_1", "source"]


MIN_INTERVAL = 0.16              # seconds between requests across all threads (SEC allows ~10 a second)
_pace = threading.Lock()
_last = [0.0]


def _get(client: httpx.Client, url: str) -> httpx.Response:
    """GET at most ~6 a second overall, backing off when the SEC throttles."""
    for attempt in range(6):
        with _pace:
            wait = _last[0] + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.monotonic()
        resp = client.get(url)
        if resp.status_code not in (429, 503):
            return resp
        time.sleep(min(120, 10 * 2 ** attempt))
    return resp


def _headers() -> dict:
    return {"User-Agent": secret("HTTP_USER_AGENT"), "Accept-Encoding": "gzip, deflate"}


def quarters(through: date) -> list[str]:
    y, q = FIRST_QUARTER
    out = []
    while (y, q) <= (through.year, (through.month - 1) // 3 + 1):
        out.append(f"{y}q{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def quarter_bounds(label: str) -> tuple[date, date]:
    y, q = int(label[:4]), int(label[-1])
    start = date(y, 3 * q - 2, 1)
    end = (date(y + 1, 1, 1) if q == 4 else date(y, 3 * q + 1, 1)) - timedelta(days=1)
    return start, end


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def parse_dataset(raw: bytes) -> pd.DataFrame:
    """Purchases in one quarterly data-set zip, one row per transaction (first reporting owner)."""
    z = zipfile.ZipFile(io.BytesIO(raw))

    def read(name: str, cols: list[str]) -> pd.DataFrame:
        """Columns that an older data set lacks (AFF10B5ONE arrived in 2023) come back empty."""
        header = z.open(name).readline().decode().rstrip("\r\n").split("\t")
        frame = pd.read_csv(z.open(name), sep="\t", dtype=str, usecols=[c for c in cols if c in header],
                            quoting=3, keep_default_na=False, on_bad_lines="skip")
        for col in cols:
            if col not in frame:
                frame[col] = ""
        return frame

    tx = read("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                     "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS",
                                     "DIRECT_INDIRECT_OWNERSHIP"])
    tx = tx[(tx["TRANS_CODE"] == "P") & (tx["TRANS_ACQUIRED_DISP_CD"] == "A")]
    sub = read("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
                                  "ISSUERTRADINGSYMBOL", "AFF10B5ONE"])
    sub = sub[sub["DOCUMENT_TYPE"].isin(["4", "4/A"])]
    own = read("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
                                      "RPTOWNER_TITLE"]).drop_duplicates("ACCESSION_NUMBER")
    df = tx.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
    rel = df["RPTOWNER_RELATIONSHIP"].fillna("")
    shares, price = _num(df["TRANS_SHARES"]), _num(df["TRANS_PRICEPERSHARE"])
    out = pd.DataFrame({
        "accn": df["ACCESSION_NUMBER"],
        "issuer_cik": _num(df["ISSUERCIK"]).astype("Int64"), "issuer_name": df["ISSUERNAME"],
        "ticker": df["ISSUERTRADINGSYMBOL"].str.upper().str.strip(),
        "owner_cik": _num(df["RPTOWNERCIK"]).astype("Int64"), "owner_name": df["RPTOWNERNAME"],
        "is_director": rel.str.contains("Director"), "is_officer": rel.str.contains("Officer"),
        "is_ten_pct": rel.str.contains("TenPercent"), "officer_title": df["RPTOWNER_TITLE"],
        "trans_date": pd.to_datetime(df["TRANS_DATE"], format="%d-%b-%Y", errors="coerce").dt.date,
        "filed": pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y", errors="coerce").dt.date,
        "shares": shares, "price": price, "value": shares * price, "shares_after": _num(df["SHRS_OWND_FOLWNG_TRANS"]),
        "direct": df["DIRECT_INDIRECT_OWNERSHIP"], "plan_10b5_1": df["AFF10B5ONE"].str.lower().eq("true"),
        "source": "dataset",
    })
    out["seq"] = out.groupby("accn").cumcount()          # transaction number within the filing
    return out.dropna(subset=["issuer_cik", "trans_date", "filed"])[COLUMNS]


def _text(node, tag: str) -> str | None:
    found = node.find(f".//{tag}/value")
    if found is None:
        found = node.find(f".//{tag}")
    return found.text.strip() if found is not None and found.text else None


def parse_form4(text: str, accn: str, filed: date) -> list[dict]:
    """Purchases in one Form 4 filing (the full-submission .txt or the bare XML)."""
    match = re.search(r"<ownershipDocument>.*?</ownershipDocument>", text, re.S)
    if not match:
        return []
    try:
        root = ET.fromstring(match.group(0))
    except ET.ParseError:
        return []
    rel = root.find(".//reportingOwnerRelationship")

    def flag(tag: str) -> bool:
        return rel is not None and (_text(rel, tag) or "0").lower() in ("1", "true")

    base = {
        "accn": accn, "issuer_cik": int(_text(root, "issuerCik") or 0), "issuer_name": _text(root, "issuerName"),
        "ticker": (_text(root, "issuerTradingSymbol") or "").upper(),
        "owner_cik": int(_text(root, "rptOwnerCik") or 0) or None, "owner_name": _text(root, "rptOwnerName"),
        "is_director": flag("isDirector"), "is_officer": flag("isOfficer"), "is_ten_pct": flag("isTenPercentOwner"),
        "officer_title": _text(rel, "officerTitle") if rel is not None else None, "filed": filed,
        "plan_10b5_1": (_text(root, "aff10b5One") or "").lower() in ("1", "true"), "source": "xml",
    }
    rows = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        if _text(tx, "transactionCode") != "P" or _text(tx, "transactionAcquiredDisposedCode") != "A":
            continue
        try:
            shares = float(_text(tx, "transactionShares") or "nan")
            price = float(_text(tx, "transactionPricePerShare") or "nan")
            after = float(_text(tx, "sharesOwnedFollowingTransaction") or "nan")
            when = date.fromisoformat((_text(tx, "transactionDate") or "")[:10])
        except ValueError:
            continue
        rows.append({**base, "seq": len(rows), "trans_date": when, "shares": shares, "price": price,
                     "value": shares * price, "shares_after": after,
                     "direct": _text(tx, "directOrIndirectOwnership")})
    return rows


def _store(con, frame: pd.DataFrame, delete_sql: str | None = None, params: list | None = None) -> None:
    with transaction(con):
        if delete_sql:
            con.execute(delete_sql, params or [])
        if not frame.empty:
            con.register("_ins", frame[COLUMNS])
            con.execute(f"INSERT OR REPLACE INTO insider_trades SELECT {', '.join(COLUMNS)} FROM _ins")
            con.unregister("_ins")


def load_datasets(con, client: httpx.Client, today: date) -> dict:
    loaded = {k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ? AND immutable",
                                        [DATASET_SOURCE]).fetchall()}
    stats = {"quarters": 0, "rows": 0}
    for label in quarters(today):
        if label in loaded:
            continue
        resp = _get(client, DATASET.format(q=label))
        if resp.status_code in (404, 429, 503):
            break                                     # not published yet (or throttled): try next run
        resp.raise_for_status()
        frame = parse_dataset(resp.content)
        start, end = quarter_bounds(label)
        # A data set covers filings made in its quarter; it replaces parsed-XML rows for those days.
        _store(con, frame, "DELETE FROM insider_trades WHERE filed BETWEEN ? AND ?", [start, end])
        log_fetch(con, DATASET_SOURCE, label, len(frame), immutable=True)
        stats["quarters"] += 1
        stats["rows"] += len(frame)
        print(f"  insiders: {label} {len(frame):,} purchases", flush=True)
    return stats


def latest_dataset_end(con) -> date | None:
    rows = [k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ? AND immutable",
                                      [DATASET_SOURCE]).fetchall()]
    return max(quarter_bounds(k)[1] for k in rows) if rows else None


def form4_paths(text: str, ciks: set[int]) -> set[tuple[str, str]]:
    """(accession, archive path) of Form 4s in a daily form index that name a tracked CIK."""
    out = set()
    for line in text.splitlines():
        if not (line.startswith("4 ") or line.startswith("4/A ")):
            continue
        parts = line.rsplit(None, 3)
        if len(parts) == 4 and parts[1].isdigit() and int(parts[1]) in ciks:
            path = parts[3]
            out.add((path.rsplit("/", 1)[-1].removesuffix(".txt"), path))
    return out


def load_days(con, client: httpx.Client, after: date, today: date, ciks: set[int]) -> dict:
    """Form 4 XML for tracked issuers, for index days after the latest data set and not yet read."""
    done = {k for (k,) in con.execute("SELECT key FROM fetch_log WHERE source = ? AND immutable",
                                      [DAY_SOURCE]).fetchall()}
    days = [d.date() for d in pd.bdate_range(after + timedelta(days=1), today) if str(d.date()) not in done]
    stats = {"days": 0, "filings": 0, "purchases": 0}

    def fetch(item: tuple[str, str], day: date) -> list[dict]:
        accn, path = item
        r = _get(client, ARCHIVE.format(path=path))
        return parse_form4(r.text, accn, day) if r.status_code == 200 else []

    for day in days:
        q = (day.month - 1) // 3 + 1
        resp = _get(client, DAILY_INDEX.format(y=day.year, q=q, d=day.strftime("%Y%m%d")))
        if resp.status_code in (403, 404):
            if day < today - timedelta(days=3):
                log_fetch(con, DAY_SOURCE, str(day), 0, immutable=True)
            continue
        resp.raise_for_status()
        filings = sorted(form4_paths(resp.text, ciks))
        rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for found in pool.map(lambda item: fetch(item, day), filings):
                rows.extend(found)
        frame = pd.DataFrame(rows, columns=COLUMNS)
        _store(con, frame)
        log_fetch(con, DAY_SOURCE, str(day), len(frame), immutable=day < today)
        stats["days"] += 1
        stats["filings"] += len(filings)
        stats["purchases"] += len(frame)
        print(f"  insiders: {day} {len(filings)} Form 4s, {len(frame)} purchases", flush=True)
    return stats


def sync(today: date | None = None) -> dict:
    today = today or date.today()
    t0 = time.time()
    con = connect()
    with httpx.Client(headers=_headers(), timeout=60, follow_redirects=True) as client:
        datasets = load_datasets(con, client, today)
        after = latest_dataset_end(con) or today - timedelta(days=30)
        days = load_days(con, client, after, today, set(tracked_ciks(con)))
    con.close()
    return {"datasets": datasets, "xml": days, "seconds": round(time.time() - t0, 1)}


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    print(sync())


if __name__ == "__main__":
    main()
