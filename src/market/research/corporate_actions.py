"""Corporate actions as events: dividend initiations, raises, cuts, specials, and spinoffs.

Dividends are the stored ones (`market.data.dividend_signals`), dated by their declaration (the
announcement, when the market learns). Spinoffs come from the S&P index change log (Wikipedia:
"... completed the corporate spin-off of ..."), dated the day the new company joined.

Each event's return starts at the next close and is measured against the average S&P 500 / 400
member over the same window (`vs universe`). Regular dividends are compared with the company's
previous regular dividend at the same frequency, skipping any pair with a split in between.
In-sample: before CUT.

Usage:  python -m market.research.corporate_actions
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.data.dividend_signals import events as dividend_events
from market.data.dividend_signals import stored
from market.research.common import (forward_excess, members_frame, spy_id, summarize, universe_mean_excess,
                                    write_report)
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HORIZONS = (21, 63, 126, 252)


def _security(con, frame: pd.DataFrame, when: str) -> pd.Series:
    hist = con.execute("SELECT security_id, ticker, valid_from, valid_to, priority FROM ticker_history").df()
    hist["valid_from"] = pd.to_datetime(hist["valid_from"])
    hist["valid_to"] = pd.to_datetime(hist["valid_to"]).fillna(pd.Timestamp.max)
    j = frame[["ticker", when]].reset_index().merge(hist, on="ticker")
    j = j[(j["valid_from"] <= j[when]) & (j["valid_to"] > j[when])].sort_values("priority").drop_duplicates("index")
    return j.set_index("index")["security_id"].reindex(frame.index)


def spinoff_events(con) -> pd.DataFrame:
    ch = con.execute("SELECT date, ticker, reason FROM universe_changes WHERE action = 'add' "
                     "AND lower(reason) LIKE '%spin%off%'").df()
    ch["date"] = pd.to_datetime(ch["date"])
    ch["security_id"] = _security(con, ch.rename(columns={"date": "on"}).assign(on=ch["date"]), "on")
    ch = ch.dropna(subset=["security_id"]).drop_duplicates("security_id")
    return pd.DataFrame({"security_id": ch["security_id"], "date": ch["date"], "type": "spinoff", "change": np.nan})


RULES = {
    "dividend initiation": lambda e: e["type"] == "initiation",
    "raise ≥ 5%": lambda e: (e["type"] == "raise") & (e["change"] >= 0.05),
    "raise ≥ 10%": lambda e: (e["type"] == "raise") & (e["change"] >= 0.10),
    "raise ≥ 20%": lambda e: (e["type"] == "raise") & (e["change"] >= 0.20),
    "raise < 5%": lambda e: (e["type"] == "raise") & (e["change"] < 0.05),
    "cut ≥ 10%": lambda e: (e["type"] == "cut") & (e["change"] <= -0.10),
    "special dividend": lambda e: e["type"] == "special",
    "spinoff (new company)": lambda e: e["type"] == "spinoff",
}


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    spy = spy_id(con)
    div, splits = stored(con)
    first = pd.to_datetime(div["ex_date"]).min()
    ev = pd.concat([dividend_events(div, splits, first), spinoff_events(con)], ignore_index=True)
    members = members_frame(con)
    # Point-in-time S&P 500 / 400 members only (a spinoff counts from the day it joined).
    j = ev.merge(members, on="security_id")
    j = j[(j["valid_from"] <= j["date"]) & (j["valid_to"] > j["date"]) | (j["type"] == "spinoff")]
    j = j.drop_duplicates(["security_id", "date", "type"]).drop(columns=["universe", "valid_from", "valid_to"])
    j = j[(j["date"] >= panel.sessions[0]) & (j["date"] <= panel.sessions[-1])]
    j = forward_excess(panel, j, spy, HORIZONS)
    base = universe_mean_excess(panel, members, sorted(j["date"].unique()), spy, HORIZONS)
    for h in HORIZONS:
        j[f"adj_{h}"] = j[f"xs_{h}"] - j["date"].map(base[h])
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None else f"{v:+.2%}"                                     # noqa: E731
    lines = [f"{len(j):,} events at S&P 500 / 400 members, {j['date'].min().date()} → {j['date'].max().date()}; "
             f"{div['declared'].notna().mean():.0%} of dividends carry a declaration date. In-sample before {CUT}. "
             "Mean excess return vs the average S&P 500 / 400 member over the same window.\n",
             "| Event | n in | 21d | 63d | 126d | 252d | hit 126d | n out | 21d | 63d | 126d | 252d | hit 126d |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    payload = {}
    for name, rule in RULES.items():
        part = j[rule(j).fillna(False)]
        cells, entry = [], {}
        for label, f in (("in", part[part["date"] < cut]), ("out", part[part["date"] >= cut])):
            stats = {h: summarize(f[f"adj_{h}"]) for h in HORIZONS}
            entry[label] = {str(h): s for h, s in stats.items()}
            hit = stats[126]["hit"]
            cells.append(f"{len(f)} | " + " | ".join(fmt(stats[h]["mean"]) for h in HORIZONS)
                         + f" | {'—' if hit is None else f'{hit:.0%}'}")
        payload[name] = entry
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    outcome = ("> **Outcome (2026-10-21).** Dividend raises ≥ 10% beat the *average* S&P 500 / 400 member in both\n"
               "> halves, but as a strategy (one lot per raise, held 126 sessions) they returned 12.2% a year vs SPY's\n"
               "> 12.1% (Sharpe 0.41 vs 0.44) — no benefit, so no Lab category was kept. Dividend cuts ≥ 10% lagged\n"
               "> badly: an input for the shorts phase. Declaration dates are now stored with the dividends.\n\n")
    print(write_report(6, "corporate-actions", "Corporate actions → forward returns", outcome + "\n".join(lines) + "\n",
                       payload))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
