"""User-defined universes from watchlists.yaml.

Each list is stored in universe_membership as `watchlist:<name>` (source 'watchlist'), so
categories, reports and the option set treat it like any other universe. Removing a ticker
from the file ends its membership on the day of the sync rather than erasing its history.

Usage:  python -m market.data.watchlists
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd
import yaml

from market.config import ROOT
from market.store.db import connect, transaction

WATCHLISTS_FILE = ROOT / "watchlists.yaml"
SOURCE = "watchlist"
PREFIX = "watchlist:"


@dataclass(frozen=True)
class Watchlist:
    name: str
    options: bool
    tickers: dict[str, date | None]       # ticker -> added date (None = undated)
    description: str = ""

    @property
    def universe(self) -> str:
        return PREFIX + self.name


def _parse_entry(entry) -> tuple[str, date | None]:
    if isinstance(entry, str):
        return entry.strip().upper(), None
    if isinstance(entry, dict) and len(entry) == 1:
        ticker, added = next(iter(entry.items()))
        added = added if isinstance(added, date) else (date.fromisoformat(str(added)) if added else None)
        return str(ticker).strip().upper(), added
    raise ValueError(f"Unrecognized watchlist entry: {entry!r}")


def load(text: str | None = None) -> list[Watchlist]:
    raw = yaml.safe_load(text if text is not None else WATCHLISTS_FILE.read_text()) or {}
    lists = []
    for name, spec in (raw.get("watchlists") or {}).items():
        spec = spec or {}
        tickers = dict(_parse_entry(e) for e in spec.get("tickers") or [])
        lists.append(Watchlist(name, bool(spec.get("options")), tickers, spec.get("description", "")))
    return lists


def sync(con: duckdb.DuckDBPyConnection, lists: list[Watchlist], today: date | None = None) -> dict[str, dict]:
    """Reconcile stored membership with the file: open new names, close removed ones."""
    today = today or date.today()
    report = {}
    with transaction(con):
        stored_lists = {
            row[0] for row in con.execute(
                "SELECT DISTINCT universe FROM universe_membership WHERE source = ?", [SOURCE]
            ).fetchall()
        }
        for wl in lists:
            current = con.execute(
                "SELECT ticker FROM universe_membership WHERE universe = ? AND source = ? AND valid_to IS NULL",
                [wl.universe, SOURCE],
            ).df()["ticker"].tolist()
            added = sorted(set(wl.tickers) - set(current))
            removed = sorted(set(current) - set(wl.tickers))
            for ticker in added:
                start = wl.tickers[ticker]
                con.execute(
                    "INSERT INTO universe_membership VALUES (?, ?, NULL, ?, NULL, ?)",
                    [wl.universe, ticker, start, SOURCE],
                )
            if removed:
                con.execute(
                    f"UPDATE universe_membership SET valid_to = ? WHERE universe = ? AND source = ? "
                    f"AND valid_to IS NULL AND ticker IN ({','.join('?' * len(removed))})",
                    [today, wl.universe, SOURCE, *removed],
                )
            report[wl.name] = {"added": added, "removed": removed, "members": len(wl.tickers), "options": wl.options}
        # A whole list deleted from the file: close all of its open memberships.
        for universe in stored_lists - {wl.universe for wl in lists}:
            con.execute(
                "UPDATE universe_membership SET valid_to = ? WHERE universe = ? AND source = ? AND valid_to IS NULL",
                [today, universe, SOURCE],
            )
            report[universe.removeprefix(PREFIX)] = {"deleted": True}
    return report


def option_tickers(lists: list[Watchlist]) -> set[str]:
    return {t for wl in lists if wl.options for t in wl.tickers}


def members(con: duckdb.DuckDBPyConnection, universe: str, on: date) -> pd.DataFrame:
    """Point-in-time members of any universe (watchlists included; 'watchlists' = all lists)."""
    clause, params = ("universe LIKE ?", [PREFIX + "%"]) if universe == "watchlists" else ("universe = ?", [universe])
    return con.execute(
        f"""SELECT DISTINCT ticker FROM universe_membership
            WHERE {clause} AND (valid_from IS NULL OR valid_from <= ?) AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY ticker""",
        [*params, on, on],
    ).df()


def main() -> None:
    lists = load()
    con = connect()
    for name, info in sync(con, lists).items():
        print(f"{name}: {info}")
    con.close()


if __name__ == "__main__":
    main()
