"""Decisions (site #/decisions): the personal position log in `positions.md`, priced against SPY.

Ported from smartmoney's Decisions page (src/generate_decisions.py), with two changes:

  * **Shares.** Every lot has a share count (default 10), so a bucket's return is dollar-weighted: what was paid
    for its lots against what they are worth now (or fetched when sold). The yardstick is a *SPY shadow*: the
    same dollars put into SPY on each lot's buy date and taken out on its sell date. Returns include dividends
    (total return) on both sides; later splits are handled (shares are as bought, prices as traded then).
  * **One row per ticker.** Several lots of a ticker in a bucket are consolidated — total shares, cost, value,
    return vs the SPY shadow of exactly those dollars — and the row expands to the individual buys, each with its
    own result, so you can see which buys beat SPY and which didn't.

File format (see positions.md): `## Bucket`, then `### Open` (`- TICKER | open-date | shares | notes`) and
`### Closed` (`- TICKER | open-date | close-date | shares | notes`). `## Archive` files everything after it away.
An open lot with no date was held longer than we know: it is graded over the last two years (`UNDATED_YEARS`).

Each row, bucket and lot also gets an **annualized** comparison: the rate of return (XIRR) on its actual cash flows
— buys out on their dates, sales and today's value back — minus the same rate for its SPY shadow. That weights each
lot by dollars × time held, so a three-year lot counts for more than a one-month one, and buckets of different ages
compare fairly. It is left blank when the money was invested for less than `MIN_ANNUALIZE_YEARS` on average.

Prices come from the panel; position tickers are added to the tracked set by the daily `signals` step
(`first_needed`), so new names get bars back to their buy dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from market.config import ROOT
from market.evaluate.metrics import trade_stats

POSITIONS_FILE = ROOT / "positions.md"
DEFAULT_SHARES = 10.0
ALIASES = {"BRKB": "BRK.B", "BRKA": "BRK.A"}   # how people write them → how the market data writes them
SERIES_STEP = 5                                 # chart points: every 5th session (plus the last)
UNDATED_YEARS = 2                               # an undated open lot is graded over this many trailing years
MIN_ANNUALIZE_YEARS = 0.25                      # dollar-weighted time invested below which no annual rate is shown

_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


@dataclass
class Lot:
    ticker: str
    open_date: date | None
    close_date: date | None
    shares: float
    notes: str = ""
    shares_given: bool = True

    @property
    def closed(self) -> bool:
        return self.close_date is not None


@dataclass
class Bucket:
    name: str
    archived: bool
    lots: list[Lot] = field(default_factory=list)


def parse_bullet(line: str, section: str | None) -> Lot | None:
    """`- TICKER | date(s) | shares | notes`. `section` ('open' / 'closed' / None = decide by the dates)."""
    parts = [p.strip() for p in line.strip()[1:].split("|")]
    ticker = ALIASES.get(parts[0].upper(), parts[0].upper())
    if not _TICKER.match(ticker):
        return None
    rest = parts[1:]
    dates: list[date | None] = []
    while rest and len(dates) < 2:
        if rest[0] == "" and not dates:            # an empty first field: an undated open lot
            rest.pop(0)
            dates.append(None)
        elif parse_date(rest[0]):
            dates.append(parse_date(rest.pop(0)))
        else:
            break
    shares, given = DEFAULT_SHARES, False
    if rest and _NUMBER.match(rest[0].replace(",", "")):
        shares, given = float(rest.pop(0).replace(",", "")), True
    notes = " | ".join(rest).strip(" |")
    dated = [d for d in dates if d is not None]
    if section == "closed" or (section is None and len(dated) == 2):
        if len(dated) < 2:
            return None                                # a closed lot needs both dates
        return Lot(ticker, dated[0], dated[1], shares, notes, given)
    return Lot(ticker, dated[0] if dated else None, None, shares, notes, given)


def parse_positions(text: str) -> list[Bucket]:
    """Buckets in file order; buckets with the same name are merged; everything after `## Archive` is archived."""
    buckets: dict[tuple[str, bool], Bucket] = {}
    current: Bucket | None = None
    section: str | None = None
    archived = False
    for raw in text.splitlines():
        line = raw.strip()
        if h2 := _H2.match(line):
            title = h2.group(1).strip()
            if title.lower() == "archive":
                archived, title = True, "Archive"
            section = None
            current = buckets.setdefault((title, archived), Bucket(title, archived))
            continue
        if h3 := _H3.match(line):
            key = h3.group(1).strip().lower()
            section = "open" if key.startswith("open") else "closed" if key.startswith("closed") else section
            continue
        if line.startswith("- ") and current is not None:
            lot = parse_bullet(line, section if not (current.archived and section is None) else None)
            if lot:
                current.lots.append(lot)
    return list(buckets.values())


def load() -> list[Bucket]:
    return parse_positions(POSITIONS_FILE.read_text()) if POSITIONS_FILE.exists() else []


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """Annual rate r with Σ cf / (1 + r)^(years since the first flow) = 0, by bisection; None if there is none."""
    if not flows or not any(cf < 0 for _, cf in flows) or not any(cf > 0 for _, cf in flows):
        return None
    t0 = min(d for d, _ in flows)
    years = np.array([(d - t0).days / 365.25 for d, _ in flows])
    cfs = np.array([cf for _, cf in flows])
    npv = lambda r: float((cfs / (1 + r) ** years).sum())
    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def annualized(lots: list[dict]) -> dict:
    """Annual rates on the lots' cash flows and on their SPY shadows, and the difference (blank when too short)."""
    priced = [l for l in lots if l["priced"]]
    cost = sum(l["cost"] for l in priced)
    if not cost:
        return {}
    avg_years = sum(l["cost"] * (l["_end"] - l["_entry"]).days / 365.25 for l in priced) / cost
    if avg_years < MIN_ANNUALIZE_YEARS:
        return {"years": avg_years}
    own = xirr([(l["_entry"], -l["cost"]) for l in priced] + [(l["_end"], l["value"]) for l in priced])
    spy = xirr([(l["_entry"], -l["cost"]) for l in priced] + [(l["_end"], l["spy_value"]) for l in priced])
    return {"years": avg_years, "ann": own, "spy_ann": spy,
            "ann_alpha": own - spy if own is not None and spy is not None else None}


def first_needed(buckets: list[Bucket] | None = None, history_start: date | None = None) -> dict[str, date]:
    """ticker → first date its prices are needed (a little before its earliest buy; undated: the history start)."""
    out: dict[str, date] = {}
    for b in buckets if buckets is not None else load():
        for lot in b.lots:
            need = lot.open_date - timedelta(days=10) if lot.open_date else history_start
            if need is not None:
                out[lot.ticker] = min(need, out.get(lot.ticker, need))
    return out


# --------------------------------------------------------------------------- pricing
def price_lot(lot: Lot, sid: str | None, panel, spy_tr: pd.Series) -> dict:
    """One lot: cost (shares × the close it was bought at), value now or at the sale, the SPY shadow of the same
    dollars over the same days, and — for a sold lot — what the stock and SPY did after the sale."""
    base = {"ticker": lot.ticker, "shares": lot.shares, "shares_given": lot.shares_given, "notes": lot.notes,
            "open": lot.open_date.isoformat() if lot.open_date else None,
            "close": lot.close_date.isoformat() if lot.close_date else None, "assumed": lot.open_date is None}
    tr = panel.tr[sid].dropna() if sid is not None and sid in panel.tr.columns else pd.Series(dtype=float)
    if tr.empty:
        return {**base, "priced": False}
    start = pd.Timestamp(lot.open_date) if lot.open_date else max(
        tr.index[0], panel.sessions[-1] - pd.DateOffset(years=UNDATED_YEARS))
    entry_i = tr.index.searchsorted(start)
    if entry_i >= len(tr):
        return {**base, "priced": False}
    entry = tr.index[entry_i]
    last = tr.index[-1]
    end = last
    if lot.close_date:
        end_i = tr.index.searchsorted(pd.Timestamp(lot.close_date))
        end = tr.index[min(end_i, len(tr) - 1)]
    raw = panel.raw_close[sid]
    cost = lot.shares * float(raw.at[entry])
    growth = float(tr.at[end] / tr.at[entry])
    spy_growth = float(spy_tr.asof(end) / spy_tr.asof(entry))
    out = {**base, "priced": True, "entry_date": entry.date().isoformat(), "end_date": end.date().isoformat(),
           "entry_px": float(raw.at[entry]), "end_px": float(raw.at[end]), "current_px": float(raw.at[last]),
           "cost": cost, "value": cost * growth, "spy_value": cost * spy_growth,
           "ret": growth - 1, "spy_ret": spy_growth - 1, "alpha": growth - spy_growth,
           "_sid": sid, "_entry": entry, "_end": end}
    out.update({k: v for k, v in annualized([out]).items() if k != "years"})
    if lot.close_date:
        after = float(tr.at[last] / tr.at[end])
        spy_after = float(spy_tr.asof(last) / spy_tr.asof(end))
        out.update({"after_ret": after - 1, "after_spy": spy_after - 1, "after_alpha": after - spy_after})
    return out


def consolidate(lots: list[dict]) -> list[dict]:
    """One row per ticker: totals and dollar-weighted returns over its lots, which are kept for the expanded view."""
    rows = []
    for ticker in dict.fromkeys(l["ticker"] for l in lots):
        group = [l for l in lots if l["ticker"] == ticker]
        priced = [l for l in group if l["priced"]]
        row = {"ticker": ticker, "lots": [{k: v for k, v in l.items() if not k.startswith("_")} for l in
                                          sorted(group, key=lambda l: l.get("entry_date") or l.get("open") or "")],
               "n": len(group), "shares": sum(l["shares"] for l in group), "priced": bool(priced),
               "first": min((l.get("entry_date") or l.get("open") or "9999") for l in group),
               "notes": "; ".join(dict.fromkeys(l["notes"] for l in group if l["notes"])),
               "assumed": any(l["assumed"] for l in group)}
        if priced:
            cost = sum(l["cost"] for l in priced)
            value = sum(l["value"] for l in priced)
            spy = sum(l["spy_value"] for l in priced)
            row.update({"cost": cost, "value": value, "spy_value": spy, "ret": value / cost - 1,
                        "spy_ret": spy / cost - 1, "alpha": (value - spy) / cost,
                        "beat": sum(l["alpha"] > 0 for l in priced), "current_px": priced[-1]["current_px"],
                        "avg_px": cost / sum(l["shares"] for l in priced)})
            row.update({k: v for k, v in annualized(priced).items() if k != "years"})
            if all("after_ret" in l for l in priced):
                after = sum(l["value"] * (1 + l["after_ret"]) for l in priced)
                after_spy = sum(l["value"] * (1 + l["after_spy"]) for l in priced)
                row.update({"after_ret": after / value - 1, "after_spy": after_spy / value - 1,
                            "after_alpha": (after - after_spy) / value})
        rows.append(row)
    return rows


def bucket_series(lots: list[dict], panel, spy_tr: pd.Series) -> dict | None:
    """Daily dollars invested, the bucket's value (sold lots frozen at their sale), and its SPY shadow."""
    priced = [l for l in lots if l["priced"]]
    if not priced:
        return None
    start = min(l["_entry"] for l in priced)
    days = panel.sessions[panel.sessions >= start]
    invested = pd.Series(0.0, index=days)
    value = pd.Series(0.0, index=days)
    spy = pd.Series(0.0, index=days)
    spy_d = spy_tr.reindex(days).ffill()
    for l in priced:
        tr = panel.tr[l["_sid"]].reindex(days).ffill()
        held = (days >= l["_entry"])
        live = held & (days <= l["_end"])
        growth = (tr / tr.at[l["_entry"]]).where(live).ffill().where(held, 0.0).fillna(0.0)
        spy_growth = (spy_d / spy_d.at[l["_entry"]]).where(live).ffill().where(held, 0.0).fillna(0.0)
        invested += np.where(held, l["cost"], 0.0)
        value += l["cost"] * growth
        spy += l["cost"] * spy_growth
    pick = list(range(0, len(days), SERIES_STEP))
    if pick[-1] != len(days) - 1:
        pick.append(len(days) - 1)
    r = lambda s: [round(float(s.iloc[i]), 2) for i in pick]
    return {"dates": [days[i].date().isoformat() for i in pick], "invested": r(invested), "value": r(value), "spy": r(spy)}


def summarize(lots: list[dict]) -> dict:
    priced = [l for l in lots if l["priced"]]
    open_ = [l for l in priced if l["close"] is None]
    closed = [l for l in priced if l["close"] is not None]
    cost = sum(l["cost"] for l in priced)
    value = sum(l["value"] for l in priced)
    spy = sum(l["spy_value"] for l in priced)
    out = {"lots": len(lots), "unpriced": sorted({l["ticker"] for l in lots if not l["priced"]}),
           "open_lots": sum(l["close"] is None for l in lots), "closed_lots": sum(l["close"] is not None for l in lots),
           "invested": cost, "value": value, "spy_value": spy,
           "ret": value / cost - 1 if cost else None, "spy_ret": spy / cost - 1 if cost else None,
           "alpha": (value - spy) / cost if cost else None,
           "open_cost": sum(l["cost"] for l in open_), "open_value": sum(l["value"] for l in open_),
           "beat": sum(l["alpha"] > 0 for l in priced), "priced": len(priced), **annualized(priced)}
    if closed:
        hold_days = pd.Series([(pd.Timestamp(l["end_date"]) - pd.Timestamp(l["entry_date"])).days for l in closed], dtype=float)
        out["closed_stats"] = trade_stats(pd.Series([l["ret"] for l in closed]), hold_days, 20)
    return out


def build(con, panel, key_of: dict) -> dict:
    from market.data.securities import security_for, ticker_map
    buckets = load()
    history = ticker_map(con)
    spy_id = con.execute("SELECT security_id FROM securities WHERE type = 'ETF' AND ticker = 'SPY'").fetchone()[0]
    spy_tr = panel.tr[spy_id].dropna()
    today = panel.sessions[-1].date()
    out = []
    for b in buckets:
        lots = []
        for lot in b.lots:
            sid = security_for(history, lot.ticker, lot.open_date or today) or security_for(history, lot.ticker, today)
            lots.append(price_lot(lot, sid, panel, spy_tr))
        open_lots = [l for l in lots if l["close"] is None]
        closed_lots = [l for l in lots if l["close"] is not None]
        out.append({"name": b.name, "archived": b.archived, "summary": summarize(lots),
                    "series": bucket_series(lots, panel, spy_tr),
                    "open": consolidate(open_lots), "closed": consolidate(closed_lots), "_lots": lots})
    every = [l for b in out for l in b.pop("_lots") if not b["archived"]]
    return {"generated_at": datetime.now().isoformat(timespec="minutes"), "data_through": today.isoformat(),
            "default_shares": DEFAULT_SHARES, "undated_years": UNDATED_YEARS, "min_annualize_years": MIN_ANNUALIZE_YEARS,
            "total": {k: v for k, v in annualized(every).items()}, "buckets": out}
