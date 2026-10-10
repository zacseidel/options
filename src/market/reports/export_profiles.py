"""Profile pages for Congress members and 13F funds that have ranked in the top PROFILE_RANK on any
report date. The set only grows; every export rebuilds each profile from the ledgers, so they stay
current without being stored per report.

members/<member_id>.json   windows (1y / 2y / since the ledger starts), disclosed dollars, rank
                           history, every copied lot with its return vs SPY, every disclosed trade
funds/<cik>.json           windows, quarterly books with follow-the-filing period returns, rank
                           history, the latest book and its exits
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from market.data.securities import STOCK_TYPES, map_tickers, ticker_map
from market.smartmoney import congress, hedge, ledgers
from market.smartmoney.signals import SmartMoney

PROFILE_RANK = 25
WINDOWS = [("1y", "1 year", 365), ("2y", "2 years (ranking)", congress.WINDOW_DAYS), ("all", "Since data starts", 3650)]
HOLDINGS_SHOWN, EXITS_SHOWN = 40, 15


def _n(v, digits=4):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    return round(float(v), digits)


def _d(v):
    return None if v is None or pd.isna(v) else pd.Timestamp(v).date().isoformat()


def _ever_ranked(con, kind: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT entity_id FROM entity_scores WHERE kind = ? AND rank <= ? GROUP BY 1 ORDER BY min(rank), 1",
        [kind, PROFILE_RANK]).fetchall()]


def _history(con, kind: str) -> dict[str, list]:
    rows = con.execute("SELECT report_date, entity_id, rank, score, features FROM entity_scores WHERE kind = ? "
                       "ORDER BY report_date", [kind]).fetchall()
    out: dict[str, list] = {}
    for d, e, rank, score, features in rows:
        f = json.loads(features)
        size = f.get("dollars") if kind == "congress" else f.get("book")
        out.setdefault(e, []).append([str(d), int(rank), _n(score), _n(size, 0)])
    return out


# ------------------------------------------------------------------ Congress

def _dollars(trades: pd.DataFrame, tx: str) -> dict:
    t = trades[trades["tx_type"] == tx]
    return {"count": int(len(t)), "mid": _n(t["amount"].fillna(0).sum(), 0),
            "lo": _n(t["amount_min"].fillna(0).sum(), 0), "hi": _n(t["amount_max"].fillna(0).sum(), 0)}


def member_profiles(con, panel, key_of: dict) -> dict[str, dict]:
    ids = _ever_ranked(con, "congress")
    if not ids:
        return {}
    sm = SmartMoney(con, panel)
    data = sm.congress.data
    as_of = panel.sessions[-1]
    pos = int(data.sessions.get_loc(as_of))
    raw = ledgers.congress_frame()
    start = raw["disclosed"].min()
    history = _history(con, "congress")
    scores = {key: congress.member_scores(data, pos, days) for key, _, days in WINDOWS}
    ranked_of = {key: int(s["rank"].notna().sum()) for key, s in scores.items()}
    lots_all = congress.lot_returns(data, pos, WINDOWS[-1][2])
    out = {}
    for mid in ids:
        mine = raw[raw["member_id"] == mid]
        if mine.empty:
            continue
        first = mine.iloc[-1]
        windows = []
        for key, label, days in WINDOWS:
            cutoff = max(as_of - pd.Timedelta(days=days), start)
            row = scores[key].loc[mid] if mid in scores[key].index else None
            in_window = mine[mine["disclosed"] >= cutoff]
            windows.append({
                "key": key, "label": label, "start": _d(cutoff),
                "rank": None if row is None or pd.isna(row["rank"]) else int(row["rank"]), "ranked_of": ranked_of[key],
                "lots": 0 if row is None else int(row["lots"]), "open_lots": 0 if row is None else int(row["open_lots"]),
                "alpha": None if row is None else _n(row["dw_alpha"]), "return": None if row is None else _n(row["dw_return"]),
                "beat_spy": None if row is None else _n(row["beat_spy"]),
                "bought": _dollars(in_window, "P"), "sold": _dollars(in_window, "S"),
            })
        lots = lots_all[lots_all["member_id"] == mid].sort_values("disclosed", ascending=False)
        exit_dates = {}
        for r in lots.itertuples():
            if not r.open:
                exit_dates[r.Index] = data.sessions[min(int(r.exit_pos), len(data.sessions) - 1)]
        out[mid] = {
            "id": mid, "name": str(first["member"]).strip(" ,"), "chamber": first["chamber"],
            "party": first.get("party") or "", "state": first.get("state") or "",
            "as_of": _d(as_of), "data_start": _d(start), "windows": windows,
            "history_fields": ["report", "rank", "alpha", "dollars"], "history": history.get(mid, []),
            "lot_fields": ["disclosed", "traded", "ticker", "key", "lo", "hi", "entry", "exit", "ret", "spy", "open"],
            "lots": [[_d(r.disclosed), _d(r.traded), r.ticker, key_of.get(r.security_id), _n(r.amount_min, 0), _n(r.amount_max, 0),
                      _d(data.sessions[int(r.pos)]), _d(exit_dates.get(r.Index)), _n(r.ret), _n(r.spy_ret), bool(r.open)]
                     for r in lots.itertuples()],
            "trade_fields": ["disclosed", "traded", "ticker", "asset", "type", "lo", "hi", "owner"],
            "trades": [[_d(r.disclosed), _d(r.traded), r.ticker, r.asset_name, r.tx_type, _n(r.amount_min, 0),
                        _n(r.amount_max, 0), r.owner or None]
                       for r in mine.sort_values("disclosed", ascending=False).itertuples()],
        }
    return out


# ------------------------------------------------------------------ 13F funds

def fund_profiles(con, key_of: dict) -> dict[str, dict]:
    ids = _ever_ranked(con, "hedge")
    if not ids:
        return {}
    signals = hedge.load_signals()
    b, periods = signals.b, signals.periods
    as_of = pd.Timestamp(con.execute("SELECT max(date) FROM calendar WHERE is_open AND date <= current_date").fetchone()[0])
    start = b.primary["filing_date"].min()
    history = _history(con, "hedge")
    stats = {key: hedge.fund_stats(periods, b, as_of, days) for key, _, days in WINDOWS}
    ranks = {}
    for key, s in stats.items():
        ranked = s[s["eligible"]].sort_values("alpha", ascending=False) if len(s) else s
        ranks[key] = ({cik: i + 1 for i, cik in enumerate(ranked.index)}, len(ranked))
    stocks = ticker_map(con)
    stocks = stocks[stocks["type"].isin(STOCK_TYPES)]

    def keys_for(tickers: pd.Series) -> list:
        sids = map_tickers(stocks, tickers.reset_index(drop=True), pd.Series([as_of] * len(tickers)))
        return [key_of.get(s) if s else None for s in sids]

    out = {}
    for cik_s in ids:
        cik = int(cik_s)
        books = b.primary[b.primary["cik"] == cik].sort_values("filing_date")
        if books.empty:
            continue
        mine = periods[periods["cik"] == cik].set_index("entry") if len(periods) else pd.DataFrame()
        session_after = lambda d: pd.Timestamp(con.execute(
            "SELECT min(date) FROM calendar WHERE is_open AND date > ?", [d.date()]).fetchone()[0] or d)
        quarters = []
        for f in books.itertuples():
            entry = session_after(f.filing_date)
            p = mine.loc[entry] if len(mine) and entry in mine.index else None
            quarters.append([_d(f.filing_date), _d(f.report_date), int(f.n), _n(f.book, 0), bool(f.gated),
                             None if p is None else _d(p["exit"]), None if p is None else _n(p["ret"]),
                             None if p is None else _n(p["spy_ret"])])
        windows = []
        for key, label, days in WINDOWS:
            s = stats[key]
            row = s.loc[cik] if len(s) and cik in s.index else None
            rank_of, n_ranked = ranks[key]
            windows.append({
                "key": key, "label": label, "start": _d(max(as_of - pd.Timedelta(days=days), start)),
                "rank": rank_of.get(cik), "ranked_of": n_ranked,
                "periods": 0 if row is None else int(row["periods"]),
                "alpha": None if row is None else _n(row["alpha"]), "return": None if row is None else _n(row["fund_return"]),
                "spy_return": None if row is None else _n(row["spy_return"]),
                "hit_rate": None if row is None else _n(row["hit_rate"]), "coverage": None if row is None else _n(row["coverage"]),
                "eligible": bool(row["eligible"]) if row is not None else False,
            })
        latest = books.iloc[-1]
        book = signals.book(int(latest["filing"]))
        new, gone = signals.changes(int(latest["filing"]))
        holdings, exits = [], []
        if book is not None and len(book):
            top = book.sort_values("weight", ascending=False).head(HOLDINGS_SHOWN)
            new_set = set(new["cusip"])
            tick = top["ticker"].fillna("")
            for r, k in zip(top.itertuples(), keys_for(tick)):
                holdings.append([r.ticker, k, r.issuer, _n(r.value, 0), _n(r.weight), r.cusip in new_set])
        if len(gone):
            g = gone.sort_values("weight", ascending=False).head(EXITS_SHOWN)
            for r, k in zip(g.itertuples(), keys_for(g["ticker"].fillna(""))):
                exits.append([r.ticker, k, r.issuer, _n(r.value, 0), _n(r.weight)])
        out[cik_s] = {
            "cik": cik_s, "name": latest["name"], "as_of": _d(as_of), "data_start": _d(start),
            "latest": {"filed": _d(latest["filing_date"]), "quarter": _d(latest["report_date"]), "positions": int(latest["n"]),
                       "book": _n(latest["book"], 0), "new": int(len(new)), "exits": int(len(gone))},
            "windows": windows,
            "history_fields": ["report", "rank", "alpha", "book"], "history": history.get(cik_s, []),
            "quarter_fields": ["filed", "quarter", "positions", "book", "gated", "exit", "ret", "spy"],
            "quarters": quarters[::-1],
            "holding_fields": ["ticker", "key", "issuer", "value", "weight", "new"], "holdings": holdings,
            "exit_fields": ["ticker", "key", "issuer", "value", "weight"], "exits": exits,
        }
    return out
