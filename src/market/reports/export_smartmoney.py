"""Congress and 13F payloads for the site, aligned to the momentum report dates.

congress.json  members, every disclosed trade (the browser buckets them by report date),
               point-in-time leaderboards (latest in full, top 25 per report date)
hedge.json     funds, the 13F filings of every fund that ranked at some report date with its
               new buys and exits, and the same leaderboards
Per stock:     Congress trades and the current top-200 funds holding it.
"""

from __future__ import annotations

import json

import duckdb
import pandas as pd

from market.data.securities import STOCK_TYPES, map_tickers, ticker_map
from market.smartmoney import hedge, ledgers

RANK_HISTORY = 25
NEW_SHOWN, EXITS_SHOWN = 8, 5


def _leaderboards(con: duckdb.DuckDBPyConnection, kind: str, dates: list[str]) -> tuple[list, list]:
    rows = con.execute("SELECT report_date, entity_id, name, rank, score, features FROM entity_scores "
                       "WHERE kind = ? ORDER BY report_date, rank", [kind]).df()
    if rows.empty:
        return [], []
    rows["report_date"] = pd.to_datetime(rows["report_date"]).dt.date.astype(str)
    index = {d: i for i, d in enumerate(dates)}
    latest = rows[rows["report_date"] == rows["report_date"].max()]
    leaders = [{"id": r.entity_id, "name": r.name, "rank": int(r.rank), "score": r.score, **json.loads(r.features),
                "as_of_report": r.report_date} for r in latest.itertuples()]
    size_key = "disclosed" if kind == "congress" else "book"
    ranks = [[index[r.report_date], r.entity_id, int(r.rank), round(r.score, 4), json.loads(r.features).get(size_key)]
             for r in rows[rows["rank"] <= RANK_HISTORY].itertuples() if r.report_date in index]
    return leaders, ranks


def _key_for(history: pd.DataFrame, key_of: dict, tickers: pd.Series, dates: pd.Series) -> list:
    sids = map_tickers(history, tickers.reset_index(drop=True), dates.reset_index(drop=True))
    return [key_of.get(s) if s else None for s in sids]


def build(con: duckdb.DuckDBPyConnection, key_of: dict[str, str], reports: list[tuple[str, str]]):
    dates = [d for d, _ in reports]
    history = ticker_map(con)
    stocks = history[history["type"].isin(STOCK_TYPES)]

    # ---------------------------------------------------------------- Congress
    trades = ledgers.congress_frame().sort_values("disclosed", ascending=False).reset_index(drop=True)
    trades["key"] = _key_for(stocks, key_of, trades["ticker"], trades["disclosed"])
    members = {m: [str(g["member"].iloc[0]).strip(" ,"), g["chamber"].iloc[0], g.get("party", pd.Series([""])).iloc[0] or "",
                   g.get("state", pd.Series([""])).iloc[0] or ""]
               for m, g in trades.groupby("member_id")}
    c_leaders, c_ranks = _leaderboards(con, "congress", dates)
    top_now = {r["id"] for r in c_leaders if r["rank"] <= 10}
    congress = {
        "reports": reports, "members": members,
        "trade_fields": ["disclosed", "traded", "member", "ticker", "key", "type", "lo", "hi", "owner"],
        "trades": [[r.disclosed.date().isoformat(), r.traded.date().isoformat() if pd.notna(r.traded) else None,
                    r.member_id, r.ticker, r.key, r.tx_type, r.amount_min, r.amount_max, r.owner or None]
                   for r in trades.itertuples()],
        "leaders": c_leaders, "rank_fields": ["report", "member", "rank", "alpha", "disclosed"], "ranks": c_ranks,
        "ledger_updated": ledgers.snapshot_info().get("congress"),
    }
    congress_by_key: dict[str, list] = {}
    for r in trades[trades["key"].notna()].itertuples():
        congress_by_key.setdefault(r.key, []).append({
            "member": members[r.member_id][0], "member_id": r.member_id, "chamber": r.chamber,
            "type": {"P": "buy", "S": "sell", "E": "exchange"}.get(r.tx_type, r.tx_type),
            "tx_date": r.traded.date().isoformat() if pd.notna(r.traded) else None,
            "disclosed": r.disclosed.date().isoformat(), "amount_lo": r.amount_min, "amount_hi": r.amount_max,
            "top": r.member_id in top_now})

    # ---------------------------------------------------------------- 13F
    signals = hedge.load_signals()
    b = signals.b
    eligible = set(signals.positions["cik"].unique()) if len(signals.positions) else set()
    first = pd.Timestamp(dates[0]) - pd.Timedelta(days=120) if dates else pd.Timestamp.min
    filings = b.primary[b.primary["cik"].isin(eligible) & (b.primary["filing_date"] >= first)].sort_values("filing_date")
    as_of_of = [(pd.Timestamp(d), pd.Timestamp(a)) for d, a in reports]

    def report_for(filed: pd.Timestamp) -> tuple[str, pd.Timestamp] | None:
        for d, a in as_of_of:
            if a >= filed:
                return d.date().isoformat(), a
        return None

    rank_cache: dict[pd.Timestamp, dict] = {}
    rows = []
    for f in filings.itertuples():
        hit = report_for(f.filing_date)
        rank = None
        if hit:
            _, as_of = hit
            if as_of not in rank_cache:
                ranked = signals.ranked(as_of)
                rank_cache[as_of] = dict(zip(ranked.index, ranked["rank"])) if len(ranked) >= hedge.MIN_RANKED else {}
            rank = rank_cache[as_of].get(f.cik)
        new, gone = signals.changes(int(f.filing))
        new = new.sort_values("weight", ascending=False).head(NEW_SHOWN)
        gone = gone.sort_values("weight", ascending=False).head(EXITS_SHOWN)
        rows.append([f.filing_date.date().isoformat(), str(f.cik), f.report_date.date().isoformat(), int(f.n),
                     float(f.book), None if rank is None else int(rank),
                     [[t, None, round(w, 4)] for t, w in zip(new["ticker"].fillna(new["issuer"]), new["weight"])],
                     [[t, None, round(w, 4)] for t, w in zip(gone["ticker"].fillna(gone["issuer"]), gone["weight"])]])
    # Link tickers to stock pages (as of today's mapping; names can predate a rename).
    tickers_seen = pd.Series(sorted({x[0] for r in rows for x in r[6] + r[7] if x[0]}))
    keys = _key_for(stocks, key_of, tickers_seen, pd.Series([pd.Timestamp.today()] * len(tickers_seen)))
    key_of_ticker = dict(zip(tickers_seen, keys))
    for r in rows:
        for x in r[6] + r[7]:
            x[1] = key_of_ticker.get(x[0])
    funds = {str(c): n for c, n in b.primary.drop_duplicates("cik", keep="last")[["cik", "name"]].itertuples(index=False)
             if c in eligible}
    h_leaders, h_ranks = _leaderboards(con, "hedge", dates)

    # The current wave: how many of today's top funds have filed for the newest quarter.
    latest_as_of = as_of_of[-1][1] if as_of_of else pd.Timestamp.today()
    top = signals.top(latest_as_of)
    latest = hedge.latest_books(b, latest_as_of, 400)
    newest_q = latest["report_date"].max() if len(latest) else None
    filed = int((latest.loc[latest.index.isin(top.index), "report_date"] == newest_q).sum()) if newest_q is not None else 0
    hedge_payload = {
        "reports": reports, "funds": funds,
        "filing_fields": ["filed", "cik", "quarter", "positions", "book", "rank", "new", "exits"],
        "filings": rows, "leaders": h_leaders, "rank_fields": ["report", "cik", "rank", "alpha", "book"], "ranks": h_ranks,
        "wave": {"quarter": None if newest_q is None else newest_q.date().isoformat(), "filed": filed, "top": int(len(top))},
        "ledger_updated": ledgers.snapshot_info().get("hedge"),
    }

    # Current top-fund holders per stock.
    holders_by_key: dict[str, list] = {}
    page_keys = set(key_of.values())
    for cik, row in latest[latest.index.isin(top.index)].iterrows():
        book = signals.book(int(row["filing"]))
        if book is None:
            continue
        new, _ = signals.changes(int(row["filing"]))
        new_set = set(new["cusip"])
        for p in book.itertuples():
            k = key_of_ticker.get(p.ticker) or (p.ticker if p.ticker in page_keys else None)
            if k:
                holders_by_key.setdefault(k, []).append({
                    "cik": str(cik), "name": row["name"], "rank": int(top.loc[cik, "rank"]),
                    "alpha": float(top.loc[cik, "alpha"]), "weight": float(p.weight), "value": float(p.value),
                    "new": p.cusip in new_set, "filed": row["filing_date"].date().isoformat()})
    for v in holders_by_key.values():
        v.sort(key=lambda r: r["rank"])
    return congress, hedge_payload, congress_by_key, holders_by_key
