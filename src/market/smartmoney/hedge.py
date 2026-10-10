"""13F hedge funds: follow-the-filing fund scores and the new-buy / alpha-driver signals.

Point-in-time throughout: a report date sees only filings public by its `as_of` session, and
a fund is judged only on holding periods that had *ended* by then.

Each fund's quarterly book (its first 13F-HR for a quarter; amendments ignored) is "bought" at
the close of the first session after its filing date and held to the same point after the
fund's next filing. Long shares only, value-weighted; unpriced positions are dropped and
counted against coverage. Period results are stored (fund_periods), and for funds that ever
rank, each position's weight and return too (fund_period_positions) so alpha attribution can
be summed for any date. Prices come from grouped-daily (adjusted) for just the sessions needed,
used once and discarded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import pandas as pd

from market.data.polygon import Polygon, PolygonError
from market.smartmoney import ledgers
from market.store.db import connect, transaction

MIN_POSITIONS, MAX_POSITIONS = 5, 150       # concentrated active books (smartmoney's band)
MIN_BOOK = 100e6
PASSIVE = ("VANGUARD", "BLACKROCK", "STATE STREET", "GEODE", "FMR ")
WINDOW_DAYS = 730
MIN_PERIODS = 3                              # = 4 filings
MIN_COVERAGE = 0.90
MIN_HIT_RATE = 0.50
TOP_FUNDS = 200
MIN_RANKED = 25                              # no fund signals until this many funds can be ranked
STALE_DAYS = 200                             # a fund that hasn't filed for this long is dropped
CURRENT_WAVE_DAYS = 135                      # a filing is "the latest book" for this long
BENCHMARK = "SPY"


@dataclass
class Books:
    primary: pd.DataFrame        # one row per (cik, quarter): filing, cik, name, filing_date, n, book, gated
    positions: pd.DataFrame      # filing, ticker, value, weight (of book)


def books() -> Books:
    filings, positions, managers = ledgers.holdings()
    original = filings[~filings["form"].str.endswith("/A")].reset_index()
    original = original.sort_values(["cik", "report_date", "filing_date"]).drop_duplicates(["cik", "report_date"])
    keep = set(original["filing"])
    pos = positions[positions["filing"].isin(keep)].copy()        # one long row per (filing, CUSIP)
    stats = pos.groupby("filing").agg(n=("value", "size"), book=("value", "sum"))
    primary = original.set_index("filing").join(stats, how="inner")
    primary["name"] = primary["cik"].astype(str).map(managers).fillna("CIK " + primary["cik"].astype(str))
    passive = primary["name"].str.upper().apply(lambda n: any(p in n for p in PASSIVE))
    primary["gated"] = primary["n"].between(MIN_POSITIONS, MAX_POSITIONS) & (primary["book"] >= MIN_BOOK) & ~passive
    pos["weight"] = pos["value"] / pos["filing"].map(primary["book"])
    return Books(primary.reset_index().sort_values(["cik", "filing_date"]), pos)


# ------------------------------------------------------------------ periods (priced once, stored)

def _sessions() -> pd.DatetimeIndex:
    con = connect()
    days = [d for (d,) in con.execute("SELECT date FROM calendar WHERE is_open ORDER BY date").fetchall()]
    con.close()
    return pd.DatetimeIndex(pd.to_datetime(days))


def candidate_periods(b: Books, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Every completed holding period of a gated book: entry and exit sessions after filings."""
    p = b.primary.copy()
    pos = sessions.searchsorted(p["filing_date"].to_numpy(), side="right")
    p["entry"] = [sessions[i] if i < len(sessions) else pd.NaT for i in pos]
    p["exit"] = p.groupby("cik")["entry"].shift(-1)
    done = p[p["gated"] & p["entry"].notna() & p["exit"].notna() & (p["exit"] > p["entry"])]
    return done[["cik", "filing", "accession", "entry", "exit", "book", "n"]]


async def _grouped(poly: Polygon, session: pd.Timestamp) -> tuple[pd.Timestamp, dict[str, float]]:
    try:
        body = await poly.get(f"/v2/aggs/grouped/locale/us/market/stocks/{session.date()}", {"adjusted": "true"})
    except PolygonError:
        return session, {}
    return session, {r["T"]: r["c"] for r in body.get("results") or [] if r.get("c")}


def grouped_closes(sessions: set[pd.Timestamp]) -> dict[pd.Timestamp, dict[str, float]]:
    async def run():
        async with Polygon() as poly:
            return dict(await asyncio.gather(*(_grouped(poly, s) for s in sorted(sessions))))
    return asyncio.run(run()) if sessions else {}


class BookIndex:
    """Positions sorted by filing with offsets: one filing's book is a cheap slice."""

    def __init__(self, positions: pd.DataFrame):
        self.rows = positions.sort_values("filing", kind="stable").reset_index(drop=True)
        keys = self.rows["filing"].to_numpy()
        self.filings, self.starts = np.unique(keys, return_index=True)
        self.ends = np.append(self.starts[1:], len(keys))

    def get(self, filing: int) -> pd.DataFrame | None:
        i = np.searchsorted(self.filings, filing)
        if i >= len(self.filings) or self.filings[i] != filing:
            return None
        return self.rows.iloc[self.starts[i]:self.ends[i]]


def _price_periods(periods: pd.DataFrame, b: Books, closes: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Period returns (all given periods) and per-position rows."""
    rows, pos_rows = [], []
    index = BookIndex(b.positions)
    for p in periods.itertuples():
        held = index.get(p.filing)
        e, x = closes.get(p.entry, {}), closes.get(p.exit, {})
        spy = (x.get(BENCHMARK) / e[BENCHMARK] - 1) if e.get(BENCHMARK) and x.get(BENCHMARK) else None
        if held is None or spy is None:
            continue
        px0 = held["ticker"].map(e)
        px1 = held["ticker"].map(x)
        ok = px0.notna() & px1.notna() & (px0 > 0)
        priced = held[ok]
        r = (px1[ok] / px0[ok] - 1).clip(-1, 20)
        value = priced["value"].sum()
        if value <= 0:
            continue
        w = priced["value"] / value
        rows.append({"cik": p.cik, "accession": p.accession, "entry": p.entry.date(), "exit": p.exit.date(),
                     "ret": float((w * r).sum()), "spy_ret": float(spy), "coverage": float(value / p.book),
                     "n_priced": int(ok.sum()), "n_total": int(p.n), "book": float(p.book)})
        pos_rows.append(pd.DataFrame({"cik": p.cik, "entry": p.entry.date(), "ticker": priced["ticker"].to_numpy(),
                                      "weight": w.to_numpy(), "ret": r.to_numpy()}))
    return pd.DataFrame(rows), (pd.concat(pos_rows, ignore_index=True) if pos_rows else pd.DataFrame())


def sync_periods(b: Books | None = None) -> dict:
    """Price any completed period not yet stored; keep positions for funds that ever rank."""
    b = b or books()
    sessions = _sessions()
    candidates = candidate_periods(b, sessions)
    con = connect()
    stored = con.execute("SELECT cik, entry FROM fund_periods").df()
    have = set(zip(stored["cik"], pd.to_datetime(stored["entry"])))
    todo = candidates[[(c, e) not in have for c, e in zip(candidates["cik"], candidates["entry"])]]
    closes = grouped_closes(set(todo["entry"]) | set(todo["exit"]))
    periods, positions = _price_periods(todo, b, closes)
    with transaction(con):
        if len(periods):
            con.register("_p", periods)
            con.execute("INSERT OR REPLACE INTO fund_periods BY NAME SELECT * FROM _p")
            con.unregister("_p")
    all_periods = con.execute("SELECT * FROM fund_periods").df()
    con.close()

    # Funds that rank on any report date need their positions for alpha attribution. Without
    # new periods only recent report dates can add a fund (its window slid), so scan just those.
    for frame in (all_periods,):
        frame["entry"], frame["exit"] = pd.to_datetime(frame["entry"]), pd.to_datetime(frame["exit"])
    recent_only = len(periods) == 0
    eligible = ever_ranked(all_periods, b, sessions[-15:] if recent_only else sessions)
    con = connect()
    stored_pos = con.execute("SELECT DISTINCT cik, entry FROM fund_period_positions").df()
    have_pos = set(zip(stored_pos["cik"], pd.to_datetime(stored_pos["entry"])))
    need = candidates[candidates["cik"].isin(eligible)]
    need = need[[(c, e) not in have_pos for c, e in zip(need["cik"], need["entry"])]]
    fresh = positions[positions["cik"].isin(eligible)] if len(positions) else positions
    fresh_keys = set(zip(fresh["cik"], pd.to_datetime(fresh["entry"]))) if len(fresh) else set()
    rest = need[[(c, e) not in fresh_keys for c, e in zip(need["cik"], need["entry"])]]
    more_sessions = (set(rest["entry"]) | set(rest["exit"])) - set(closes)
    closes.update(grouped_closes(more_sessions))
    _, extra = _price_periods(rest, b, closes)
    keep = pd.concat([f for f in (fresh, extra) if len(f)], ignore_index=True) if (len(fresh) or len(extra)) else None
    with transaction(con):
        if keep is not None and len(keep):
            con.register("_q", keep)
            con.execute("INSERT OR REPLACE INTO fund_period_positions BY NAME SELECT * FROM _q")
            con.unregister("_q")
    con.close()
    return {"periods_priced": len(periods), "sessions_fetched": len(closes), "eligible_funds": len(eligible),
            "position_rows": 0 if keep is None else len(keep)}


# ------------------------------------------------------------------ point-in-time ranking

def fund_stats(periods: pd.DataFrame, b: Books, as_of: pd.Timestamp, window_days: int | None = None) -> pd.DataFrame:
    """Every fund's follow-the-filing record over completed periods in the window, with an `eligible`
    flag (the ranking gates) — unranked funds included, for profile pages."""
    window = periods[(pd.to_datetime(periods["exit"]) <= as_of)
                     & (pd.to_datetime(periods["entry"]) >= as_of - pd.Timedelta(days=window_days or WINDOW_DAYS))]
    if window.empty:
        return pd.DataFrame()
    window = window.assign(g=1 + window["ret"], gs=1 + window["spy_ret"],
                           win=(window["ret"] > window["spy_ret"]).astype(float),
                           cv=window["coverage"] * window["book"])
    g = window.groupby("cik")
    funds = pd.DataFrame({
        "periods": g.size(),
        "fund_return": g["g"].prod() - 1,
        "spy_return": g["gs"].prod() - 1,
        "hit_rate": g["win"].mean(),
        "coverage": g["cv"].sum() / g["book"].sum(),
    })
    funds["alpha"] = funds["fund_return"] - funds["spy_return"]
    latest = latest_books(b, as_of, max_age_days=STALE_DAYS)
    funds = funds.join(latest[["name", "filing_date", "gated", "book"]], how="inner")
    funds["eligible"] = ((funds["periods"] >= MIN_PERIODS) & (funds["coverage"] >= MIN_COVERAGE)
                         & (funds["hit_rate"] > MIN_HIT_RATE) & (funds["alpha"] > 0) & funds["gated"])
    return funds


def rank_funds(periods: pd.DataFrame, b: Books, as_of: pd.Timestamp, window_days: int | None = None) -> pd.DataFrame:
    """Funds ranked by follow-the-filing alpha over periods that ended by `as_of`."""
    funds = fund_stats(periods, b, as_of, window_days)
    if funds.empty:
        return funds
    ranked = funds[funds["eligible"]].sort_values("alpha", ascending=False).drop(columns="eligible")
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    return ranked


def latest_books(b: Books, as_of: pd.Timestamp, max_age_days: int) -> pd.DataFrame:
    """Each fund's newest book public by `as_of` (filed on or before it), if recent enough."""
    p = b.primary[(b.primary["filing_date"] <= as_of)
                  & (b.primary["filing_date"] > as_of - pd.Timedelta(days=max_age_days))]
    return p.sort_values("filing_date").groupby("cik").tail(1).set_index("cik")


def ever_ranked(periods: pd.DataFrame, b: Books, sessions: pd.DatetimeIndex) -> set[int]:
    ciks: set[int] = set()
    for as_of in _report_sessions(sessions):
        ranked = rank_funds(periods, b, as_of)
        ciks |= set(ranked.index[:TOP_FUNDS])
    return ciks


def _report_sessions(sessions: pd.DatetimeIndex) -> list[pd.Timestamp]:
    from market.reports.snapshot import report_dates
    start = sessions[0].date()
    out = []
    for d in report_dates(start, sessions[-1].date() + pd.Timedelta(days=4)):
        i = sessions.searchsorted(pd.Timestamp(d), side="left") - 1
        if i >= 0:
            out.append(sessions[i])
    return sorted(set(out))


# ------------------------------------------------------------------ signals

class HedgeSignals:
    """Per-report cache shared by the categories and the export."""

    def __init__(self, b: Books, periods: pd.DataFrame, positions: pd.DataFrame):
        self.b = b
        self.periods = periods
        self.positions = positions
        self._index = BookIndex(b.positions)
        self._pos = self._index.rows
        self.prev_filing = b.primary.assign(prev=b.primary.groupby("cik")["filing"].shift(1)).set_index("filing")["prev"]
        self._ranked: dict[pd.Timestamp, pd.DataFrame] = {}

    def book(self, filing: int) -> pd.DataFrame | None:
        return self._index.get(filing)

    def ranked(self, as_of: pd.Timestamp) -> pd.DataFrame:
        if as_of not in self._ranked:
            self._ranked[as_of] = rank_funds(self.periods, self.b, as_of)
        return self._ranked[as_of]

    def top(self, as_of: pd.Timestamp) -> pd.DataFrame:
        ranked = self.ranked(as_of)
        return ranked.head(TOP_FUNDS) if len(ranked) >= MIN_RANKED else ranked.iloc[0:0]

    def changes(self, filing: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(new positions, exited positions) of a filing vs. the fund's previous book."""
        cur = self.book(filing)
        prev_id = self.prev_filing.get(filing)
        prev = self.book(int(prev_id)) if pd.notna(prev_id) else None
        if cur is None:
            cur = self._pos.iloc[0:0]
        if prev is None:
            return cur.iloc[0:0], cur.iloc[0:0]
        new = cur[~cur["cusip"].isin(prev["cusip"])]
        gone = prev[~prev["cusip"].isin(cur["cusip"])]
        return new, gone

    def new_buys(self, as_of: pd.Timestamp) -> pd.DataFrame:
        """Positions new in the top funds' latest books, scored Σ alpha × hit rate × weight."""
        top = self.top(as_of)
        latest = latest_books(self.b, as_of, CURRENT_WAVE_DAYS)
        latest = latest[latest.index.isin(top.index)].reset_index()
        latest["prev"] = latest["filing"].map(self.prev_filing)
        latest = latest.dropna(subset=["prev"])
        if latest.empty:
            return pd.DataFrame(columns=["score"])
        pos = self._pos
        cur = pos[pos["filing"].isin(latest["filing"])].merge(latest[["filing", "cik", "prev", "filing_date"]], on="filing")
        prev = pos[pos["filing"].isin(latest["prev"])][["filing", "cusip"]].rename(columns={"filing": "prev"})
        prev["held"] = True
        cur = cur.merge(prev, on=["prev", "cusip"], how="left")
        new = cur[cur["held"].isna() & cur["ticker"].notna()].copy()
        if new.empty:
            return pd.DataFrame(columns=["score"])
        new["fund"] = new["cik"].map(top["name"])
        new["points"] = new["cik"].map(top["alpha"] * top["hit_rate"]) * new["weight"]
        new = new.sort_values("points", ascending=False)
        g = new.groupby("ticker", sort=False)
        out = pd.DataFrame({
            "score": g["points"].sum(),
            "funds": g.size().astype(float),
            "value": g["value"].sum(),
            "issuer": g["issuer"].first(),
            "last_filed": g["filing_date"].max().dt.date.astype(str),
        })
        out["top_funds"] = new.groupby("ticker", sort=False).head(3).groupby("ticker", sort=False)["fund"].agg(", ".join)
        return out.sort_values("score", ascending=False)

    @property
    def contributions(self) -> pd.DataFrame:
        """Each stored position's contribution to its fund's alpha, computed once:
        growth before the period × weight × (position return − SPY return)."""
        if not hasattr(self, "_contrib"):
            per = self.periods[self.periods["cik"].isin(self.positions["cik"].unique())].sort_values(["cik", "entry"])
            growth = np.log1p(per["ret"].clip(lower=-0.99))
            per = per.assign(before=np.exp(growth.groupby(per["cik"]).cumsum() - growth))
            pos = self.positions.merge(per[["cik", "entry", "exit", "before", "spy_ret"]], on=["cik", "entry"])
            pos["contribution"] = pos["before"] * pos["weight"] * (pos["ret"] - pos["spy_ret"])
            self._contrib = pos[["cik", "entry", "exit", "ticker", "contribution"]]
        return self._contrib

    def drivers(self, as_of: pd.Timestamp) -> pd.DataFrame:
        """Names that contributed most to the top funds' alpha, among names they still hold."""
        top = self.top(as_of)
        if top.empty:
            return pd.DataFrame(columns=["score"])
        c = self.contributions
        c = c[c["cik"].isin(top.index) & (c["exit"] <= as_of) & (c["entry"] >= as_of - pd.Timedelta(days=WINDOW_DAYS))]
        latest = latest_books(self.b, as_of, CURRENT_WAVE_DAYS)
        latest = latest[latest.index.isin(top.index)]
        books_held = [bk[["ticker", "issuer"]] for bk in (self.book(int(f)) for f in latest["filing"]) if bk is not None]
        if c.empty or not books_held:
            return pd.DataFrame(columns=["score"])
        held = pd.concat(books_held)
        holders = held.groupby("ticker").size()
        c = c[c["ticker"].isin(holders.index)]
        g = c.groupby("ticker")
        out = pd.DataFrame({
            "score": g["contribution"].sum(),
            "funds": g["cik"].nunique().astype(float),
        })
        out["held_by"] = holders.reindex(out.index).astype(float)
        out["issuer"] = held.drop_duplicates("ticker").set_index("ticker")["issuer"].reindex(out.index)
        return out[out["score"] > 0].sort_values("score", ascending=False)


def load_signals(b: Books | None = None) -> HedgeSignals:
    b = b or books()
    con = connect()
    periods = con.execute("SELECT * FROM fund_periods").df()
    positions = con.execute("SELECT * FROM fund_period_positions").df()
    con.close()
    for frame in (periods, positions):
        if len(frame):
            frame["entry"] = pd.to_datetime(frame["entry"])
    if len(periods):
        periods["exit"] = pd.to_datetime(periods["exit"])
    return HedgeSignals(b, periods, positions)
