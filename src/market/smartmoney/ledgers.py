"""Read-only access to smartmoney's raw ledgers (decision D3: read the ledgers in place).

Raw inputs only — Congress transactions, 13F holdings, the CUSIP→ticker map. Every score,
ranking and category is computed here from these, point-in-time; smartmoney's own derived
outputs (rankings, fund performance) are used only for display fall-backs. Nothing is copied
into the database.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

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


def stamp(relative: str) -> float:
    """mtime of a ledger file, so callers can tell when it changed."""
    file = _root() / relative
    return file.stat().st_mtime if file.exists() else 0.0


TRANSACTIONS = "data/transactions.json"
HOLDINGS = "data/hedge/holdings.json.gz"
CUSIP_MAP = "data/cache/cusip/cusip_map.json.gz"
CUSIP_OVERRIDES = "data/hedge/cusip_overrides.json"


# ------------------------------------------------------------------ Congress

@lru_cache(maxsize=1)
def congress_transactions() -> list[dict]:
    ledger = _load(TRANSACTIONS) or {}
    return list(ledger.values()) if isinstance(ledger, dict) else ledger


def congress_frame() -> pd.DataFrame:
    """One row per disclosed transaction with a ticker: buys (P), sales (S), exchanges (E)."""
    rows = [t for t in congress_transactions() if t.get("ticker") and t.get("disclosure_date")]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["ticker"] = frame["ticker"].str.upper().str.strip()
    frame["member"] = frame["member"].astype(str).str.strip(" ,")
    frame["disclosed"] = pd.to_datetime(frame["disclosure_date"], errors="coerce")
    frame["traded"] = pd.to_datetime(frame["tx_date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount_mid"), errors="coerce").fillna(
        (pd.to_numeric(frame["amount_min"], errors="coerce") + pd.to_numeric(frame["amount_max"], errors="coerce")) / 2)
    keep = ["tx_id", "chamber", "member", "member_id", "party", "state", "ticker", "asset_name", "owner",
            "tx_type", "traded", "disclosed", "amount", "amount_min", "amount_max", "source_url"]
    return frame[[c for c in keep if c in frame.columns]].dropna(subset=["disclosed"])


# ------------------------------------------------------------------ 13F

@lru_cache(maxsize=1)
def cusip_tickers() -> dict[str, str]:
    mapping = {k.upper(): v.get("ticker") for k, v in (_load(CUSIP_MAP) or {}).items() if v and v.get("ticker")}
    for cusip, record in (_load(CUSIP_OVERRIDES) or {}).items():
        ticker = record.get("ticker") if isinstance(record, dict) else record
        if ticker:
            mapping[cusip.upper()] = ticker
    return mapping


@lru_cache(maxsize=1)
def holdings() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """The 13F ledger, kept columnar (2.7M rows load in a few seconds).

    Returns (filings, positions, managers):
      filings   one row per filing: filing (index), cik, filing_date, report_date, form, accession
      positions long-share rows only: filing, ticker (None when the CUSIP is unresolved), cusip,
                issuer, value
      managers  cik → name
    """
    raw = _load(HOLDINGS)
    if not raw:
        return pd.DataFrame(), pd.DataFrame(), {}
    filings = pd.DataFrame(raw["filings"], columns=["cik", "filing_date", "report_date", "form", "accession"])
    filings["filing_date"] = pd.to_datetime(filings["filing_date"])
    filings["report_date"] = pd.to_datetime(filings["report_date"])
    filings.index.name = "filing"
    securities = pd.DataFrame(raw["securities"], columns=["cusip", "issuer"])
    tickers = cusip_tickers()
    securities["ticker"] = (securities["cusip"].str.upper().map(tickers).str.strip().str.upper()
                            .str.replace("/", ".", regex=False).str.replace(" ", ".", regex=False))
    put_call = np.array([0 if p in (0, None) else 1 for p in raw["put_call"]], dtype=np.int8)
    sec_idx = np.asarray(raw["sec_idx"])
    long = put_call == 0
    positions = pd.DataFrame({
        "filing": np.asarray(raw["filing_idx"])[long],
        "sec": sec_idx[long],
        "value": np.asarray(raw["value"], dtype=float)[long],
    })
    positions["ticker"] = securities["ticker"].to_numpy()[positions["sec"]]
    positions["cusip"] = securities["cusip"].to_numpy()[positions["sec"]]
    positions["issuer"] = securities["issuer"].to_numpy()[positions["sec"]]
    managers = {str(k): v for k, v in raw["managers"].items()}
    return filings, positions.drop(columns="sec"), managers


# ------------------------------------------------------------------ display fall-backs

@lru_cache(maxsize=1)
def hedge_stock_holders() -> dict:
    return _load("data/hedge/stock_holders.json.gz") or {}


def snapshot_info() -> dict:
    """When each ledger last changed, for page footers."""
    from datetime import datetime
    return {name: datetime.fromtimestamp(stamp(rel)).isoformat(timespec="minutes") if stamp(rel) else None
            for name, rel in (("congress", TRANSACTIONS), ("hedge", HOLDINGS))}


def clear_cache() -> None:
    for fn in (congress_transactions, cusip_tickers, holdings, hedge_stock_holders):
        fn.cache_clear()
