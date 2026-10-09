"""Phase 0 probe: what does this Polygon plan actually include, and how big is the option panel?

Usage:  python -m market.ops.probe [--universe-dir ../momentum10/data/universe]

Prints a report and writes data/state/probe-YYYY-MM-DD.json. Read-only: nothing is stored
in the market database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

from market.config import ROOT, config, directory
from market.data import flatfiles
from market.data.options import filter_panel, option_root
from market.data.polygon import NotEntitled, Polygon, PolygonError

PROBE_TICKER = "AAPL"


@dataclass
class Check:
    name: str
    ok: bool | None          # None = not run / unknown
    detail: str
    data: dict = field(default_factory=dict)


def weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def years_ago(n: float, today: date) -> date:
    return weekday_on_or_before(today - timedelta(days=round(365.25 * n)))


async def grouped(poly: Polygon, session: date) -> dict:
    return await poly.get(
        f"/v2/aggs/grouped/locale/us/market/stocks/{session}", {"adjusted": "false"}
    )


async def find_session(poly: Polygon, start: date, tries: int = 6) -> tuple[date | None, dict | None, str]:
    """Walk back from `start` to the first session with grouped data."""
    d = weekday_on_or_before(start)
    last_error = ""
    for _ in range(tries):
        try:
            body = await grouped(poly, d)
            if body.get("resultsCount", 0) > 0:
                return d, body, ""
        except NotEntitled as exc:
            # Free/delayed plans refuse the current session until end of day; step back.
            if "before end of day" not in exc.message:
                return None, None, f"not entitled: {exc.message}"
            last_error = f"not entitled: {exc.message}"
        except PolygonError as exc:
            last_error = str(exc)
        d = weekday_on_or_before(d - timedelta(days=1))
    return None, None, last_error or "no data"


# --------------------------------------------------------------------------- stocks


async def check_stocks(poly: Polygon, today: date, checks: list[Check]) -> tuple[date | None, dict]:
    latest, body, err = await find_session(poly, today)
    if latest is None:
        checks.append(Check("stocks.grouped_latest", False, err))
        return None, {}
    rows = body["results"]
    has_vwap = sum(1 for r in rows if r.get("vw") is not None) / len(rows)
    checks.append(Check(
        "stocks.grouped_latest", True,
        f"{latest}: {len(rows):,} tickers, VWAP on {has_vwap:.0%} of rows",
        {"session": str(latest), "rows": len(rows), "vwap_share": round(has_vwap, 3)},
    ))
    closes = {r["T"]: r["c"] for r in rows if r.get("c")}

    depth = {}
    for n in (2, 4, 5, 6):
        session, _, err = await find_session(poly, years_ago(n, today))
        depth[n] = str(session) if session else f"no ({err})"
    deepest = max((n for n, v in depth.items() if not v.startswith("no")), default=None)
    checks.append(Check(
        "stocks.grouped_depth", deepest is not None and deepest >= 5,
        f"grouped daily available back to ~{deepest} yr" if deepest else "no history",
        {"by_years": depth},
    ))

    start = years_ago(6, today)
    try:
        aggs = await poly.get(
            f"/v2/aggs/ticker/{PROBE_TICKER}/range/1/day/{start}/{today}",
            {"adjusted": "false", "limit": 50000, "sort": "asc"},
        )
        res = aggs.get("results") or []
        first = datetime.fromtimestamp(res[0]["t"] / 1000, tz=timezone.utc).date() if res else None
        checks.append(Check("stocks.aggs_depth", bool(res), f"{PROBE_TICKER} daily bars from {first} ({len(res)} bars)"))
    except PolygonError as exc:
        checks.append(Check("stocks.aggs_depth", False, str(exc)))

    for name, endpoint in (("splits", "/v3/reference/splits"), ("dividends", "/v3/reference/dividends")):
        try:
            body = await poly.get(endpoint, {"limit": 5})
            checks.append(Check(f"stocks.{name}", True, f"{len(body.get('results') or [])} sample rows"))
        except PolygonError as exc:
            checks.append(Check(f"stocks.{name}", False, str(exc)))

    try:
        body = await poly.get(f"/v3/reference/tickers/{PROBE_TICKER}", {"date": str(years_ago(3, today))})
        res = body.get("results") or {}
        fields = {k: res.get(k) is not None for k in ("market_cap", "share_class_shares_outstanding", "sic_code", "composite_figi")}
        checks.append(Check("stocks.details_point_in_time", all(fields.values()), f"fields present: {fields}"))
    except PolygonError as exc:
        checks.append(Check("stocks.details_point_in_time", False, str(exc)))

    try:
        body = await poly.get("/vX/reference/tickers/META/events")
        events = (body.get("results") or {}).get("events") or []
        checks.append(Check("stocks.ticker_events", bool(events), f"META events: {[e.get('type') for e in events][:5]}"))
    except PolygonError as exc:
        checks.append(Check("stocks.ticker_events", False, str(exc)))

    try:
        body = await poly.get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{PROBE_TICKER}")
        updated_ns = (body.get("ticker") or {}).get("updated")
        age = (time.time() - updated_ns / 1e9) / 60 if updated_ns else None
        checks.append(Check("stocks.snapshot", True, f"updated {age:.0f} min ago" if age is not None else "no timestamp"))
    except PolygonError as exc:
        checks.append(Check("stocks.snapshot", False, str(exc)))

    return latest, closes


# --------------------------------------------------------------------------- options


async def pick_contract(poly: Polygon, as_of: date) -> str | None:
    rows = await poly.paginate(
        "/v3/reference/options/contracts",
        {
            "underlying_ticker": PROBE_TICKER,
            "as_of": str(as_of),
            "contract_type": "put",
            "expiration_date.gte": str(as_of + timedelta(days=25)),
            "expiration_date.lte": str(as_of + timedelta(days=50)),
            "limit": 250,
        },
        max_pages=1,
    )
    return rows[len(rows) // 2]["ticker"] if rows else None


async def check_options(poly: Polygon, today: date, checks: list[Check]) -> None:
    depth = {}
    sample_contract = None
    for n in (1, 2, 3, 4, 5):
        as_of = years_ago(n, today)
        try:
            contract = await pick_contract(poly, as_of)
            if not contract:
                depth[n] = "no contracts listed"
                continue
            body = await poly.get(f"/v2/aggs/ticker/{contract}/range/1/day/{as_of}/{as_of + timedelta(days=10)}")
            bars = body.get("resultsCount", 0)
            depth[n] = f"ok ({contract}, {bars} bars)" if bars else f"no bars ({contract})"
            sample_contract = sample_contract or contract
        except NotEntitled as exc:
            depth[n] = f"not entitled: {exc.message}"
        except PolygonError as exc:
            depth[n] = f"error: {exc}"
    deepest = max((n for n, v in depth.items() if v.startswith("ok")), default=None)
    checks.append(Check(
        "options.aggs_depth", deepest is not None,
        f"per-contract daily bars back to ~{deepest} yr" if deepest else "no option history",
        {"by_years": depth},
    ))

    try:
        body = await poly.get(
            f"/v3/snapshot/options/{PROBE_TICKER}",
            {
                "expiration_date.gte": str(today + timedelta(days=25)),
                "expiration_date.lte": str(today + timedelta(days=50)),
                "contract_type": "put",
                "limit": 50,
            },
        )
        res = body.get("results") or []
        first = res[0] if res else {}
        present = {
            "greeks": bool(first.get("greeks")),
            "implied_volatility": first.get("implied_volatility") is not None,
            "open_interest": first.get("open_interest") is not None,
            "last_quote_bid_ask": bool((first.get("last_quote") or {}).get("bid")),
            "day_bar": bool(first.get("day")),
            "day_vwap": (first.get("day") or {}).get("vwap") is not None,
        }
        checks.append(Check("options.snapshot", bool(res), f"{len(res)} contracts; fields: {present}", present))
    except PolygonError as exc:
        checks.append(Check("options.snapshot", False, str(exc)))

    if sample_contract:
        try:
            await poly.get(f"/v3/quotes/{sample_contract}", {"limit": 1})
            checks.append(Check("options.historical_quotes", True, "entitled"))
        except NotEntitled:
            checks.append(Check("options.historical_quotes", False, "not entitled (expected below Advanced) — use spread haircut"))
        except PolygonError as exc:
            checks.append(Check("options.historical_quotes", False, str(exc)))


# --------------------------------------------------------------------------- throughput


async def check_concurrency(checks: list[Check], n: int = 32) -> None:
    """Burst of cheap calls with retries off: a paid plan serves all; the free tier 429s after 5."""
    async with Polygon(max_retries=0) as burst:
        started = time.perf_counter()
        results = await asyncio.gather(
            *(burst.get(f"/v3/reference/tickers/{PROBE_TICKER}") for _ in range(n)), return_exceptions=True
        )
        elapsed = time.perf_counter() - started
    limited = sum(1 for r in results if isinstance(r, PolygonError) and r.status == 429)
    checks.append(Check(
        "api.concurrency", limited == 0,
        f"{n} calls in {elapsed:.1f}s ({n / elapsed:.0f}/s), {limited} rate-limited"
        + (" — key is still rate-limited (free tier?)" if limited else ""),
    ))


# --------------------------------------------------------------------------- flat files


def load_universe_roots(universe_dir: Path) -> set[str]:
    roots: set[str] = set()
    for name in ("sp500.csv", "sp400.csv"):
        file = universe_dir / name
        if file.exists():
            roots |= {option_root(str(s)) for s in pd.read_csv(file)["symbol"].dropna() if str(s)[0].isalpha()}
    return roots


def check_flatfiles(
    today: date, latest: date | None, closes: dict[str, float], universe_dir: Path, checks: list[Check]
) -> None:
    if not flatfiles.available():
        checks.append(Check(
            "flatfiles.access", None,
            "skipped — set POLYGON_S3_ACCESS_KEY_ID / POLYGON_S3_SECRET_ACCESS_KEY in .env "
            "(dashboard → Flat Files) to measure the option panel",
        ))
        return

    depth = {}
    for n in (1, 2, 3, 4, 5):
        d = years_ago(n, today)
        size = None
        for _ in range(5):
            size = flatfiles.head("options_day", d)
            if size:
                break
            d = weekday_on_or_before(d - timedelta(days=1))
        depth[n] = f"{d}: {size / 1e6:.1f} MB" if size else "missing / not entitled"
    deepest = max((n for n, v in depth.items() if "MB" in v), default=None)
    checks.append(Check("flatfiles.options_depth", deepest is not None,
                        f"options day files back to ~{deepest} yr" if deepest else "no access", {"by_years": depth}))

    session = latest
    if session is None:
        return
    # Today's options file posts ~11:00 ET the next day; fall back one session if missing.
    for _ in range(4):
        if flatfiles.head("options_day", session):
            break
        session = weekday_on_or_before(session - timedelta(days=1))
    started = time.perf_counter()
    frame, compressed = flatfiles.read_day("options_day", session)
    roots = load_universe_roots(universe_dir)
    spot = {option_root(t): c for t, c in closes.items() if option_root(t) in roots}
    kept = filter_panel(frame, session, spot, config()["options"]["panel"])

    scratch = directory("state") / "probe_panel.duckdb"
    scratch.unlink(missing_ok=True)
    with duckdb.connect(str(scratch)) as con:
        table = kept[["ticker", "root", "expiry", "type", "strike", "dte", "open", "high", "low", "close", "volume", "transactions"]]
        con.register("kept", table)
        con.execute("""
            CREATE TABLE option_bars AS
            SELECT ticker, root, CAST(expiry AS DATE) AS expiry, type, CAST(strike AS DOUBLE) AS strike,
                   CAST(dte AS SMALLINT) AS dte, CAST(open AS FLOAT) AS open, CAST(high AS FLOAT) AS high,
                   CAST(low AS FLOAT) AS low, CAST(close AS FLOAT) AS close,
                   CAST(volume AS INTEGER) AS volume, CAST(transactions AS INTEGER) AS transactions
            FROM kept
        """)
        con.execute("CHECKPOINT")
    db_bytes = scratch.stat().st_size
    scratch.unlink(missing_ok=True)

    per_year = 252
    years = {"starter_2y": 2, "developer_4y": 4}
    est = {k: f"{len(kept) * per_year * y / 1e6:.1f}M rows, ~{db_bytes * per_year * y / 1e9:.2f} GB"
           for k, y in years.items()}
    checks.append(Check(
        "flatfiles.panel_size", True,
        f"{session}: file {compressed / 1e6:.1f} MB, {len(frame):,} contracts → kept {len(kept):,} "
        f"for {kept['root'].nunique()} of {len(roots)} roots; one day ≈ {db_bytes / 1e6:.1f} MB in DuckDB "
        f"(includes fixed overhead); parse+filter {time.perf_counter() - started:.1f}s",
        {"session": str(session), "rows_total": len(frame), "rows_kept": len(kept),
         "compressed_bytes": compressed, "duckdb_bytes_one_day": db_bytes, "estimates": est},
    ))


# --------------------------------------------------------------------------- main


async def run(universe_dir: Path) -> list[Check]:
    today = date.today()
    checks: list[Check] = []
    # Burst first: if the key is rate-limited, every later check would crawl through retries.
    await check_concurrency(checks)
    if checks[-1].ok is False:
        checks.append(Check("probe.aborted", False, "upgrade the key (or set the paid key in .env) and re-run"))
        return checks
    async with Polygon() as poly:
        latest, closes = await check_stocks(poly, today, checks)
        await check_options(poly, today, checks)
        calls = poly.calls
    check_flatfiles(today, latest, closes, universe_dir, checks)
    checks.append(Check("probe.calls", True, f"{calls} REST calls"))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--universe-dir", type=Path, default=ROOT.parent / "momentum10" / "data" / "universe")
    args = parser.parse_args()

    checks = asyncio.run(run(args.universe_dir))
    mark = {True: "✅", False: "❌", None: "⏭️ "}
    for c in checks:
        print(f"{mark[c.ok]} {c.name:32} {c.detail}")
        for key, value in (c.data.get("by_years") or {}).items():
            print(f"{'':36}{key} yr: {value}")
    out = directory("state") / f"probe-{date.today()}.json"
    out.write_text(json.dumps([asdict(c) for c in checks], indent=2, default=str))
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
