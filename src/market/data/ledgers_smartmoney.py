"""Read-only access to smartmoney's Congress and 13F outputs (decision D3: read the ledgers).

Display only for now — these feed the Smart Money page and the stock pages, not categories
or evaluations. Everything is read in place from the smartmoney repo; nothing is copied
into the database.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from market.config import path


def _root() -> Path:
    return path("smartmoney_repo")


def _load(relative: str):
    file = _root() / relative
    if not file.exists():
        return None
    opener = gzip.open if file.suffix == ".gz" else open
    with opener(file, "rt") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def congress_rankings() -> dict:
    return _load("data/rankings.json") or {}


@lru_cache(maxsize=1)
def congress_transactions() -> list[dict]:
    ledger = _load("data/transactions.json") or {}
    return list(ledger.values()) if isinstance(ledger, dict) else ledger


@lru_cache(maxsize=1)
def hedge_rankings() -> dict:
    return _load("data/hedge/rankings.json") or {}


@lru_cache(maxsize=1)
def hedge_stock_holders() -> dict:
    return _load("data/hedge/stock_holders.json.gz") or {}


def congress_trades_by_ticker() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    outperformers = set(congress_rankings().get("outperformer_ids") or [])
    for tx in congress_transactions():
        ticker = tx.get("ticker")
        if not ticker:
            continue
        out.setdefault(ticker, []).append({
            "member": tx.get("member"), "member_id": tx.get("member_id"), "chamber": tx.get("chamber"),
            "type": {"P": "buy", "S": "sell"}.get(tx.get("tx_type"), tx.get("tx_type")),
            "tx_date": tx.get("tx_date"), "disclosed": tx.get("disclosure_date"),
            "amount_lo": tx.get("amount_min"), "amount_hi": tx.get("amount_max"),
            "outperformer": tx.get("member_id") in outperformers,
        })
    for rows in out.values():
        rows.sort(key=lambda r: r.get("disclosed") or "", reverse=True)
    return out


def snapshot_info() -> dict:
    """When each source was last generated, for the page footers."""
    return {
        "congress": congress_rankings().get("generated"),
        "hedge": hedge_rankings().get("generated"),
    }
