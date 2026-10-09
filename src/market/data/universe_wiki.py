"""Historical S&P 500 / S&P 400 membership rebuilt from Wikipedia (decision D4).

Each index has a constituents table (today's members) and a dated change table
(added / removed tickers). Replaying the changes backward from today's members yields
membership intervals. Inconsistencies (a ticker removed while not a member, added while
already one) are returned as anomalies — usually renames (FB→META) that ticker_history
resolves once securities are loaded.

Usage:  python -m market.data.universe_wiki [--universe sp500 sp400]
"""

from __future__ import annotations

import argparse
import io
import re
from dataclasses import dataclass
from datetime import date

import httpx
import pandas as pd

from market.config import secret
from market.store.db import connect, log_fetch, replace_rows

WIKI = "https://en.wikipedia.org/wiki/"
PAGES = {
    "sp500": {"constituents": "List_of_S%26P_500_companies", "changes": "Historical_components_of_the_S%26P_500"},
    "sp400": {"constituents": "List_of_S%26P_400_companies", "changes": "List_of_S%26P_400_companies"},
}
SOURCE = "wikipedia"


@dataclass
class Replay:
    intervals: pd.DataFrame      # ticker, valid_from, valid_to
    anomalies: list[dict]


def clean_tickers(value) -> list[str]:
    """Wikipedia cell → tickers. Drops footnotes and notes ('VSCO (NOW VSXY)'), splits 'UA/UAA'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = re.sub(r"\[.*?\]|\(.*?\)", "", str(value)).upper()
    return [t for t in (part.strip() for part in text.split("/")) if t]


def clean_ticker(value) -> str | None:
    tickers = clean_tickers(value)
    return tickers[0] if tickers else None


def _read_tables(page: str) -> list[pd.DataFrame]:
    user_agent = secret("HTTP_USER_AGENT", required=False) or "market-research/0.1"
    resp = httpx.get(WIKI + page, headers={"User-Agent": user_agent}, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def parse_constituents(tables: list[pd.DataFrame]) -> pd.DataFrame:
    table = next(t for t in tables if "Symbol" in t.columns)
    out = pd.DataFrame({"ticker": table["Symbol"].map(clean_ticker), "name": table["Security"]})
    return out.dropna(subset=["ticker"]).drop_duplicates("ticker").reset_index(drop=True)


def parse_changes(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Flatten the two-row header change table into one row per add/drop event."""
    table = next(t for t in tables if isinstance(t.columns, pd.MultiIndex) and "Added" in t.columns.get_level_values(0))
    date_col = next(c for c in table.columns if "date" in str(c[0]).lower())
    reason_col = next((c for c in table.columns if str(c[0]).lower() == "reason"), None)
    events = []
    for _, row in table.iterrows():
        when = pd.to_datetime(row[date_col], errors="coerce")
        if pd.isna(when):
            continue
        reason = row[reason_col] if reason_col is not None else None
        for group, action in (("Added", "add"), ("Removed", "drop")):
            for ticker in clean_tickers(row[(group, "Ticker")]):
                events.append({
                    "date": when.date(), "action": action, "ticker": ticker,
                    "name": row[(group, "Security")] if pd.notna(row[(group, "Security")]) else None,
                    "reason": re.sub(r"\[.*?\]", "", str(reason)).strip() if pd.notna(reason) else None,
                })
    frame = pd.DataFrame(events, columns=["date", "action", "ticker", "name", "reason"])
    return frame.drop_duplicates(["date", "action", "ticker"]).reset_index(drop=True)


def replay(current: set[str], changes: pd.DataFrame) -> Replay:
    """Walk changes newest → oldest, undoing each, to recover membership intervals."""
    members = set(current)
    open_until: dict[str, date | None] = {t: None for t in current}   # ticker -> valid_to of its open interval
    intervals, anomalies = [], []

    for when, day in sorted(changes.groupby("date"), key=lambda item: item[0], reverse=True):
        # Undo adds first: before `when` the added ticker was not a member.
        for ticker in day.loc[day["action"] == "add", "ticker"]:
            if ticker in members:
                intervals.append((ticker, when, open_until.pop(ticker)))
                members.discard(ticker)
            else:
                anomalies.append({"date": when, "ticker": ticker, "issue": "added but not a member afterwards"})
        # Then undo drops: before `when` the removed ticker was a member.
        for ticker in day.loc[day["action"] == "drop", "ticker"]:
            if ticker in members:
                anomalies.append({"date": when, "ticker": ticker, "issue": "removed but still a member afterwards"})
                continue
            members.add(ticker)
            open_until[ticker] = when

    # Whoever is left was a member since before the change history begins.
    intervals.extend((ticker, None, valid_to) for ticker, valid_to in open_until.items())
    frame = pd.DataFrame(intervals, columns=["ticker", "valid_from", "valid_to"])
    return Replay(frame.sort_values(["ticker", "valid_from"], na_position="first").reset_index(drop=True), anomalies)


def resolve_membership(con, universes: list[str] | None = None) -> dict[str, dict]:
    """Re-replay each universe on security ids, so renames (FB→META, GPS→GAP) join up.

    Runs after the security master exists. Each change event's ticker is mapped to the
    security using that ticker on that date; today's members by today's tickers.
    """
    from market.data.securities import security_for, ticker_map, tickers_on   # avoid import cycle

    history = ticker_map(con)
    today_map = tickers_on(history, date.today())
    report = {}
    resolved: dict[str, tuple[pd.DataFrame, list[dict], list[str]]] = {}
    universes = universes or list(PAGES)
    for universe in universes:
        changes = con.execute(
            "SELECT date, action, ticker FROM universe_changes WHERE universe = ? AND source = ?", [universe, SOURCE]
        ).df()
        changes["date"] = pd.to_datetime(changes["date"]).dt.date
        current = con.execute(
            "SELECT ticker FROM universe_membership WHERE universe = ? AND source = ? AND valid_to IS NULL",
            [universe, SOURCE],
        ).df()["ticker"]
        current_ids = {today_map.get(t) or security_for(history, t, date.today()) or f"?{t}" for t in current}
        ids = [security_for(history, t, d) or f"?{t}" for t, d in zip(changes["ticker"], changes["date"])]
        result = replay(current_ids, changes.assign(ticker=ids))
        resolved[universe] = (changes.assign(security_id=ids), result.anomalies, result)

    # Moves between indexes are often recorded only on the destination's page (TWLO joined the
    # S&P 400 in 2025 and moved to the S&P 500 in 2026 with no S&P 400 removal row). An
    # "added but not a member afterwards" anomaly closes at the security's next addition elsewhere.
    for universe in universes:
        changes, anomalies, result = resolved[universe]
        others = pd.concat([resolved[u][0] for u in universes if u != universe]) if len(universes) > 1 else None
        repaired = []
        for a in anomalies:
            if a["issue"] != "added but not a member afterwards" or others is None or str(a["ticker"]).startswith("?"):
                continue
            later = others[(others["security_id"] == a["ticker"]) & (others["action"] == "add") & (others["date"] > a["date"])]
            if len(later):
                repaired.append({"ticker": a["ticker"], "valid_from": a["date"], "valid_to": later["date"].min()})
        if repaired:
            result.intervals = pd.concat([result.intervals, pd.DataFrame(repaired)], ignore_index=True)
            result.anomalies = [a for a in anomalies if a["ticker"] not in {r["ticker"] for r in repaired}]

        id_to_ticker = con.execute("SELECT security_id, ticker FROM securities").df().set_index("security_id")["ticker"]
        intervals = result.intervals.rename(columns={"ticker": "security_id"})
        changes = changes.drop(columns=["security_id"])
        ids = list(resolved[universe][0]["security_id"])
        intervals["ticker"] = intervals["security_id"].map(id_to_ticker).fillna(intervals["security_id"].str.lstrip("?"))
        intervals.loc[intervals["security_id"].str.startswith("?"), "security_id"] = None
        out = intervals.assign(universe=universe, source=SOURCE)[
            ["universe", "ticker", "security_id", "valid_from", "valid_to", "source"]
        ]
        replace_rows(con, "universe_membership", out, "universe = ? AND source = ?", [universe, SOURCE])
        cov = coverage(intervals.rename(columns={"ticker": "_t", "security_id": "ticker"}).fillna({"ticker": "?"}),
                       date(date.today().year - 5, 1, 1), date.today())
        report[universe] = {
            "anomalies": result.anomalies,
            "unmapped": sorted({t for t, i in zip(changes["ticker"], ids) if i.startswith("?")}),
            "coverage_min": int(cov["members"].min()), "coverage_max": int(cov["members"].max()),
        }
    return report


def members_on(intervals: pd.DataFrame, when: date) -> set[str]:
    when = pd.Timestamp(when)
    starts, ends = pd.to_datetime(intervals["valid_from"]), pd.to_datetime(intervals["valid_to"])
    starts_ok = starts.isna() | (starts <= when)
    ends_ok = ends.isna() | (ends > when)
    return set(intervals.loc[starts_ok & ends_ok, "ticker"])


def coverage(intervals: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Member count at each month end — a quick sanity check (expect ~503 / ~400)."""
    month_ends = pd.date_range(start, end, freq="ME").date
    return pd.DataFrame({"date": month_ends, "members": [len(members_on(intervals, d)) for d in month_ends]})


def sync(universes: list[str]) -> dict[str, dict]:
    report = {}
    con = connect()
    for universe in universes:
        pages = PAGES[universe]
        constituents_tables = _read_tables(pages["constituents"])
        change_tables = (
            constituents_tables if pages["changes"] == pages["constituents"] else _read_tables(pages["changes"])
        )
        current = parse_constituents(constituents_tables)
        changes = parse_changes(change_tables)
        result = replay(set(current["ticker"]), changes)

        changes_out = changes.assign(universe=universe, source=SOURCE)[
            ["universe", "date", "action", "ticker", "name", "reason", "source"]
        ]
        membership_out = result.intervals.assign(universe=universe, source=SOURCE, security_id=None)[
            ["universe", "ticker", "security_id", "valid_from", "valid_to", "source"]
        ]
        replace_rows(con, "universe_changes", changes_out, "universe = ? AND source = ?", [universe, SOURCE])
        replace_rows(con, "universe_membership", membership_out, "universe = ? AND source = ?", [universe, SOURCE])
        log_fetch(con, f"wiki_{universe}", str(date.today()), len(changes), immutable=False)

        cov = coverage(result.intervals, date(date.today().year - 5, 1, 1), date.today())
        report[universe] = {
            "current_members": len(current),
            "change_events": len(changes),
            "history_starts": str(changes["date"].min()),
            "intervals": len(result.intervals),
            "anomalies": result.anomalies,
            "coverage_min": int(cov["members"].min()),
            "coverage_max": int(cov["members"].max()),
            "coverage": cov,
        }
    con.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild S&P membership history from Wikipedia")
    parser.add_argument("--universe", nargs="+", default=list(PAGES), choices=list(PAGES))
    parser.add_argument("--resolve", action="store_true", help="re-replay on security ids (needs securities)")
    args = parser.parse_args()
    if args.resolve:
        con = connect()
        for universe, info in resolve_membership(con, args.universe).items():
            recent = [a for a in info["anomalies"] if a["date"].year >= date.today().year - 6]
            print(f"{universe}: 5-yr member count {info['coverage_min']}–{info['coverage_max']}; "
                  f"{len(recent)} anomalies in the last 6 years; unmapped tickers: {len(info['unmapped'])}")
            for a in recent:
                print(f"      {a['date']}  {a['ticker']:14} {a['issue']}")
        con.close()
        return
    for universe, info in sync(args.universe).items():
        print(f"{universe}: {info['current_members']} members today, {info['change_events']} change events "
              f"since {info['history_starts']}, {info['intervals']} intervals")
        print(f"   5-yr month-end member count: {info['coverage_min']}–{info['coverage_max']}")
        recent = [a for a in info["anomalies"] if a["date"].year >= date.today().year - 6]
        print(f"   anomalies: {len(info['anomalies'])} total, {len(recent)} in the last 6 years")
        for a in recent[:25]:
            print(f"      {a['date']}  {a['ticker']:6} {a['issue']}")


if __name__ == "__main__":
    main()
