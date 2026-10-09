"""Option contract helpers and the option-panel filter (PLAN §4).

OCC tickers encode the contract terms: O:AAPL261120P00150000 is the AAPL put expiring
2026-11-20 with a $150 strike. Parsing them means the flat-file rows carry everything we
need, so no contract-reference calls are required to build the panel.
"""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

OCC_RE = re.compile(r"^O:(?P<root>[A-Z0-9]+?)(?P<expiry>\d{6})(?P<type>[CP])(?P<strike>\d{8})$")


def occ_ticker(root: str, expiry: date, kind: str, strike: float) -> str:
    return f"O:{root}{expiry:%y%m%d}{kind}{round(strike * 1000):08d}"


def parse_occ(tickers: pd.Series) -> pd.DataFrame:
    """Vectorized OCC parse → root, expiry (date), type ('C'/'P'), strike. Unparseable rows are NaN."""
    parts = tickers.str.extract(OCC_RE)
    out = pd.DataFrame(index=tickers.index)
    out["root"] = parts["root"]
    out["expiry"] = pd.to_datetime(parts["expiry"], format="%y%m%d", errors="coerce")
    out["type"] = parts["type"]
    out["strike"] = pd.to_numeric(parts["strike"], errors="coerce") / 1000.0
    return out


def option_root(stock_ticker: str) -> str:
    """OCC root for a stock ticker (class shares drop the dot: BRK.B → BRKB)."""
    return stock_ticker.replace(".", "").replace("-", "")


PANEL_COLUMNS = ["session", "root", "expiry", "kind", "strike", "open", "close", "volume", "transactions"]


def filter_panel(
    rows: pd.DataFrame,
    session: date,
    spot_by_root: dict[str, float],
    bands: dict,
) -> pd.DataFrame:
    """Reduce one OPRA day-aggregates file to the option panel (PLAN §4).

    rows: flat-file frame (ticker, open, close, volume, transactions, ...);
    spot_by_root: the session's underlying close keyed by OCC root — only these
    underlyings are kept, so this is where the select option set is enforced.
    Adjusted/non-standard roots (e.g. AAPL1) never match a root and are dropped.
    Returns PANEL_COLUMNS; the OCC ticker is not stored (rebuild it with occ_ticker).
    """
    terms = parse_occ(rows["ticker"])
    spot = terms["root"].map(spot_by_root)
    dte = (terms["expiry"] - pd.Timestamp(session)).dt.days
    moneyness = terms["strike"] / spot
    is_put = terms["type"].eq("P")
    is_call = terms["type"].eq("C")

    short = dte.between(*bands["short_dte"])
    short_put = short & is_put & moneyness.between(*bands["put_strike_pct"])
    short_call = short & is_call & moneyness.between(*bands["call_strike_pct"])
    leap_call = is_call & dte.between(*bands["leap_dte"]) & moneyness.between(*bands["leap_call_strike_pct"])
    keep = spot.notna() & (short_put | short_call | leap_call) & (rows["volume"] >= bands.get("min_volume", 0))

    return pd.DataFrame({
        "session": pd.Timestamp(session),
        "root": terms.loc[keep, "root"],
        "expiry": terms.loc[keep, "expiry"],
        "kind": terms.loc[keep, "type"],
        "strike": terms.loc[keep, "strike"],
        "open": rows.loc[keep, "open"].astype(np.float32),
        "close": rows.loc[keep, "close"].astype(np.float32),
        "volume": rows.loc[keep, "volume"].astype(np.int32),
        "transactions": rows.loc[keep, "transactions"].astype(np.int32),
    })[PANEL_COLUMNS]
