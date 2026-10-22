"""Newsfeed (site #/news): the lists worth acting on, what they hold, and what changes at each report.

  1. **Inclusion.** Each candidate list (config `newsfeed.candidates`) is included only while its
     since-inception Sharpe beats SPY's over the same dates — re-checked every run from the evaluation.
  2. **The lists.** For each included list, its names on the latest report: held, next in line, or — for a
     filtered list, shown with its full base list — skipped by the filter, with the filter's reading. Every
     name shows when it joined the list (current unbroken stretch) and its gain since.
  3. **Allocation.** Each held stock gets its list's half-Kelly (0.5 · (win rate − loss rate ÷ payoff), from
     the list's closed trades). A stock on several lists appears on each, flagged, and is sized once, at the
     lowest of those half-Kellys. If the total is above 100% everything is scaled down to 100%; if below,
     the rest sits in SPY. No stock above `cap`.
  4. **Reports.** Per report: Buy / Add / Trim / Sell / Hold per stock vs the previous report, with each
     list's reason and, for positions a list closes, that trade's result vs SPY.

Like every data file, it is encrypted when the site pass phrase is set (`market.reports.site_lock`).
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from market.categories.option_flow import OptionFlow, iv_table
from market.categories.registry import REGISTRY
from market.categories.short_interest import ShortInterest, crowding
from market.config import config
from market.evaluate.engine import load_strategies
from market.evaluate.metrics import performance
from market.methods.hold_rules import fill_price
from market.reports.snapshot import upcoming_report
from market.research.common import members_frame

HOLDS = ("while_listed", "fixed_hold")
FILTER_LABEL = {"short_interest": "short-interest filter", "iv": "IV filter"}


def _pct(v, signed=True) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:+.0f}%" if signed else f"{v * 100:.0f}%"


def feature_text(features: dict) -> str:
    """One short phrase from a list row's features, for the 'why' column."""
    f = features or {}
    if f.get("return_12m") is not None and f.get("avg_rank") is None:
        return f"12-month return {_pct(f['return_12m'])}"
    if f.get("avg_rank") is not None:
        return f"average 3/6/12-month rank {f['avg_rank']:.1f}"
    if f.get("longevity") is not None:
        return f"{round(f['longevity'] * 26)}/26 weeks in the top 50"
    if f.get("fmom") is not None:
        return f"fundamental score {f['fmom']:.2f}, 12-month rank {f.get('rank_12m') or 0:.0f}"
    if f.get("gross_margin_chg") is not None:
        return f"gross margin {f['gross_margin_chg'] * 100:+.1f} pts"
    if f.get("return_3m") is not None:
        return f"3-month return {_pct(f['return_3m'])}"
    return ""


def _sessions_index(sessions: pd.DatetimeIndex, d) -> int:
    """Index of the session on/after `d` (len(sessions) for a date after the last stored session)."""
    return int(sessions.searchsorted(pd.Timestamp(d)))


def holdings(strategy, snaps: pd.DataFrame, report: pd.Timestamp, sessions: pd.DatetimeIndex) -> dict:
    """security_id → {weight, lots, row}: what the strategy holds after acting on `report`."""
    slot = strategy.slot
    rows = snaps if slot == "all" else snaps[snaps["rank"].between(slot[0], slot[1])]
    out: dict[str, dict] = {}
    if strategy.hold == "while_listed":
        for r in rows[rows["report_date"] == report].itertuples(index=False):
            out[r.security_id] = {"lots": 1, "row": r}
    else:
        n = strategy.params["sessions"]
        idx = _sessions_index(sessions, report)
        for r in rows[rows["report_date"] <= report].itertuples(index=False):
            e = _sessions_index(sessions, r.report_date)
            if e <= idx < e + n:
                cur = out.setdefault(r.security_id, {"lots": 0, "row": r})
                cur["lots"] += 1
                cur["row"] = r
    total = sum(v["lots"] for v in out.values())
    for v in out.values():
        v["weight"] = v["lots"] / total
    return out


def allocate(held_by: dict[str, list[str]], kelly: dict[str, float], cap: float) -> tuple[dict, dict]:
    """held_by: stock → lists holding it. Each stock's raw size is the lowest half-Kelly of its lists; the
    total is scaled down to 100% if larger (else the rest is SPY), then no stock above `cap` (the excess
    goes to the uncapped stocks while there is room, else to SPY). Returns (weights, info)."""
    raw = {sid: min(kelly[l] for l in lists) for sid, lists in held_by.items()}
    total = sum(raw.values())
    scale = 1 / total if total > 1 else 1.0
    w = {sid: r * scale for sid, r in raw.items()}
    capped: set[str] = set()
    for _ in range(len(w) + 1):
        over = [s for s, v in w.items() if v > cap + 1e-12]
        if not over:
            break
        excess = sum(w[s] - cap for s in over)
        for s in over:
            w[s] = cap
            capped.add(s)
        room = [s for s in w if s not in capped]
        base = sum(w[s] for s in room)
        if base <= 0:
            break
        target = min(sum(raw[s] * scale for s in room) + excess, cap * len(room))
        for s in room:
            w[s] = w[s] / base * min(target, base + excess)
    return w, {"raw": raw, "total_raw": total, "scale": scale, "capped": capped, "spy": max(0.0, 1 - sum(w.values()))}


def _streak_start(snaps: pd.DataFrame, sid: str, report: pd.Timestamp, all_reports: list) -> pd.Timestamp | None:
    """First report of the stock's current unbroken run on a list (snaps: one category's rows)."""
    dates = set(snaps.loc[snaps["security_id"] == sid, "report_date"])
    if report not in dates:
        return None
    start = report
    for d in reversed([d for d in all_reports if d < report]):
        if d not in dates:
            break
        start = d
    return start


def build(con, panel, key_of: dict) -> dict:
    cfg = config()["newsfeed"]
    rf = config()["evaluation"]["risk_free_rate"]
    by_id = {s.id: s for s in load_strategies()}
    sessions = panel.sessions
    metrics = {sid: json.loads(js) for sid, js in con.execute(
        "SELECT strategy_id, metrics FROM strategy_metrics WHERE window_name = 'all'").fetchall()}
    navs = con.execute("SELECT strategy_id, date, nav FROM nav_daily").df()
    navs["date"] = pd.to_datetime(navs["date"])
    navs = navs.pivot(index="date", columns="strategy_id", values="nav")

    # 1. Inclusion: since-inception Sharpe vs SPY over the same dates.
    candidates, included = [], []
    for c in cfg["candidates"]:
        s = by_id.get(c["strategy"])
        if s is None or s.hold not in HOLDS or s.instrument != "stock" or s.id not in navs:
            continue
        m = metrics.get(s.id, {})
        nav = navs[s.id].dropna()
        spy = navs["bench.SPY"].reindex(nav.index).dropna()
        spy_sharpe = performance(spy, rf).get("sharpe") if len(spy) > 20 else None
        hk = m.get("half_kelly")
        ok = m.get("sharpe") is not None and spy_sharpe is not None and m["sharpe"] > spy_sharpe and (hk or 0) > 0
        reason = (f"Sharpe {m.get('sharpe', 0):.2f} beats SPY's {spy_sharpe:.2f} over the same dates" if ok else
                  f"Sharpe {m.get('sharpe') or 0:.2f} does not beat SPY's {spy_sharpe or 0:.2f} over the same dates"
                  if (hk or 0) > 0 else "no positive half-Kelly yet")
        entry = {"id": s.id, "name": REGISTRY[s.category].name, "category": s.category, "stage": s.stage,
                 "base": c.get("base"), "base_name": REGISTRY[c["base"]].name if c.get("base") else None,
                 "filter": c.get("filter"), "slot": s.slot, "hold": s.hold, "sessions": s.params.get("sessions"),
                 "included": ok, "reason": reason,
                 "metrics": {k: m.get(k) for k in ("start", "cagr", "sharpe", "max_drawdown", "half_kelly", "win_rate",
                                                   "payoff_ratio", "closed_trades", "median_hold_days")},
                 "spy_sharpe": spy_sharpe}
        candidates.append(entry)
        if ok:
            included.append((s, entry))
    kelly = {s.id: e["metrics"]["half_kelly"] for s, e in included}

    cats = sorted({s.category for s, _ in included} | {e["base"] for _, e in included if e["base"]})
    snaps = con.execute(f"SELECT category_id, report_date, as_of, security_id, ticker, rank, features "
                        f"FROM category_snapshots WHERE origin = 'backtest' AND category_id IN "
                        f"({','.join('?' * len(cats))})", cats).df()
    snaps["report_date"] = pd.to_datetime(snaps["report_date"])
    snaps["features"] = snaps["features"].map(json.loads)
    by_cat = {c: g for c, g in snaps.groupby("category_id")}
    empty = snaps.iloc[0:0]
    trades = con.execute("SELECT strategy_id, security_id, signal_date, entry_date, exit_signal_date, exit_date, "
                         "return_total, status FROM trades WHERE strategy_id IN "
                         f"({','.join('?' * len(included))})", [s.id for s, _ in included]).df()
    for col in ("signal_date", "entry_date", "exit_signal_date", "exit_date"):
        trades[col] = pd.to_datetime(trades[col])
    spy_tr = panel.tr[con.execute("SELECT security_id FROM securities WHERE type = 'ETF' AND ticker = 'SPY'").fetchone()[0]]
    names = dict(con.execute("SELECT security_id, name FROM securities").fetchall())
    members = members_frame(con)
    filters = {"short_interest": ShortInterest(con, panel) if any(e["filter"] == "short_interest" for _, e in included) else None,
               "iv": OptionFlow(con, panel) if any(e["filter"] == "iv" for _, e in included) else None}

    upcoming = upcoming_report(panel)
    all_reports = sorted(d for d in snaps["report_date"].unique() if d.weekday() in (1, 4))
    shown = all_reports[-(cfg["reports"] + 1):]
    latest = shown[-1]

    def members_on(universe, d):
        m = members[(members["valid_from"] <= d) & (members["valid_to"] > d)]
        return m[m["universe"].isin(universe)]["security_id"].unique()

    def as_of(report) -> pd.Timestamp:
        return sessions[min(_sessions_index(sessions, report), len(sessions)) - 1]

    filter_cache: dict = {}

    def filter_reading(kind, report, sid) -> str | None:
        """Why the filter skips `sid` on `report`, or None if it doesn't."""
        key = (kind, report)
        if key not in filter_cache:
            d = as_of(report)
            if kind == "short_interest":
                filter_cache[key] = crowding(filters[kind], d, members_on(["sp500"], d))
            else:
                filter_cache[key] = iv_table(filters[kind], d, members_on(["sp500", "sp400"], d))
        table = filter_cache[key]
        if table is None or sid not in table.index:
            return None
        r = table.loc[sid]
        if kind == "short_interest" and r["crowded"]:
            return f"heavily shorted: {r['days_to_cover']:.1f} days to cover (top {max(1, round(100 - r['dtc_pct'] * 100))}% of the S&P 500)"
        if kind == "iv" and r["warned"]:
            return f"options price {r['iv_rv']:.1f}× its realized volatility (top {max(1, round(100 - r['iv_rv_pct'] * 100))}% of the S&P 500 / 400)"
        return None

    def spy_return(start, end) -> float | None:
        before = spy_tr.loc[:start - pd.Timedelta(days=1)].dropna()
        after = spy_tr.loc[:end].dropna()
        return float(after.iloc[-1] / before.iloc[-1] - 1) if len(before) and len(after) else None

    def exit_result(strategy, sid, report, held_row) -> dict | None:
        t = trades[(trades["strategy_id"] == strategy.id) & (trades["security_id"] == sid)]
        t = t[t["exit_signal_date"] == report] if strategy.hold == "while_listed" else t[t["signal_date"] == held_row.report_date]
        if t.empty:
            return None
        t = t.sort_values("entry_date").iloc[-1]
        end = t["exit_date"] if pd.notna(t["exit_date"]) else sessions[-1]
        return {"entry": t["entry_date"].date().isoformat(), "pending": t["status"] == "open",
                "return": round(float(t["return_total"]), 4), "spy": spy_return(t["entry_date"], end),
                "days": int((end - t["entry_date"]).days)}

    def state(report):
        per = {s.id: holdings(s, by_cat.get(s.category, empty), report, sessions) for s, _ in included}
        held_by: dict[str, list[str]] = {}
        for s, _ in included:
            for sid in per[s.id]:
                held_by.setdefault(sid, []).append(s.id)
        weights, info = allocate(held_by, kelly, cfg["cap"])
        return weights, per, held_by, info

    states = {d: state(d) for d in shown}
    list_name = {s.id: e["name"] for s, e in included}

    # 3. Allocation after the latest report, with an explanation per stock.
    w1, p1, held1, info1 = states[latest]
    allocation = []
    for sid, w in sorted(w1.items(), key=lambda kv: -kv[1]):
        lists = held1[sid]
        low = min(lists, key=lambda l: kelly[l])
        parts = " / ".join(f"{list_name[l]} {kelly[l]:.0%}" for l in lists)
        source = f"lowest of {parts}" if len(lists) > 1 else list_name[low]
        explain = f"half-Kelly {kelly[low]:.1%} ({source})"
        if info1["scale"] < 1:
            explain += f" × {info1['scale']:.2f} to fit 100%"
        if sid in info1["capped"]:
            explain += f" → capped at {cfg['cap']:.0%}"
        allocation.append({"key": key_of.get(sid, sid), "name": names.get(sid), "weight": round(w, 4),
                           "raw": round(info1["raw"][sid], 4), "lists": [list_name[l] for l in lists],
                           "duplicate": len(lists) > 1, "explain": explain})

    # 2. The lists on the latest report.
    lists_out = []
    last_close = panel.close.iloc[-1]
    open_trades = trades[trades["status"] == "open"]
    for s, e in included:
        shown_cat = e["base"] or s.category
        rows = by_cat.get(shown_cat, empty)
        today = rows[rows["report_date"] == latest].sort_values("rank")
        top = today[today["rank"] <= cfg["depth"]] if s.slot != "all" or s.hold != "fixed_hold" else today
        held = p1[s.id]
        extra = [sid for sid in held if sid not in set(top["security_id"])]
        own = by_cat.get(s.category, empty)
        own_today = own[own["report_date"] == latest].set_index("security_id")
        out_rows = []
        for r in top.itertuples(index=False):
            out_rows.append(_list_row(r.security_id, int(r.rank), r.features, s, e, held, own_today, rows, latest,
                                      all_reports, sessions, panel, last_close, key_of, names, w1, held1, list_name,
                                      filter_reading, open_trades))
        for sid in extra:
            row = own[(own["security_id"] == sid)].sort_values("report_date").iloc[-1] if not own[own["security_id"] == sid].empty else None
            out_rows.append(_list_row(sid, None, row["features"] if row is not None else {}, s, e, held, own_today,
                                      own, latest, all_reports, sessions, panel, last_close, key_of, names, w1, held1,
                                      list_name, filter_reading, open_trades))
        lists_out.append({"id": s.id, "name": e["name"], "shown": REGISTRY[shown_cat].name,
                          "filter": FILTER_LABEL.get(e["filter"]), "half_kelly": kelly[s.id], "rows": out_rows})

    # 4. Reports.
    reports_out = []
    for prev, cur in zip(shown[:-1], shown[1:]):
        (w0, p0, _, _), (wc, pc, _, infoc) = states[prev], states[cur]
        actions = []
        for sid in sorted(set(w0) | set(wc)):
            a, b = w0.get(sid, 0.0), wc.get(sid, 0.0)
            ins, outs = [], []
            for s, e in included:
                h0, h1 = p0[s.id].get(sid), pc[s.id].get(sid)
                label = e["name"]
                if h1 and (not h0 or h1["lots"] > h0["lots"]):
                    r = h1["row"]
                    why = f"#{int(r.rank)} on {label}" if s.slot != "all" else f"listed on {label}"
                    ft = feature_text(r.features)
                    ins.append({"list": label, "why": why + (f" — {ft}" if ft else "")})
                if h0 and (not h1 or h1["lots"] < h0["lots"]):
                    why = _exit_reason(s, e, sid, cur, by_cat, empty, filter_reading)
                    outs.append({"list": label, "why": why, "result": exit_result(s, sid, cur, h0["row"])})
            change = b - a
            if a == 0:
                action = "Buy"
            elif b == 0:
                action = "Sell"
            elif abs(change) < cfg["min_change"] and not ins and not outs:
                continue
            elif change >= cfg["min_change"]:
                action = "Add"
            elif change <= -cfg["min_change"]:
                action = "Trim"
            else:
                action = "Hold"
            note = None
            if not ins and not outs:
                note = "rebalance: the same lists, resized because the number of positions changed"
            elif a and b and not ins and outs and change > 0:
                note = "larger because the remaining list's half-Kelly is higher (a stock is sized at its lists' lowest)"
            actions.append({"key": key_of.get(sid, sid), "name": names.get(sid), "action": action,
                            "before": round(a, 4), "after": round(b, 4), "in": ins, "out": outs, "note": note})
        order = {"Buy": 0, "Add": 1, "Trim": 2, "Sell": 3, "Hold": 4}
        actions.sort(key=lambda x: (order[x["action"]], -x["after"], x["key"]))
        reports_out.append({"date": cur.date().isoformat(), "as_of": as_of(cur).date().isoformat(),
                            "upcoming": upcoming is not None and cur.date() == upcoming,
                            "filled": _sessions_index(sessions, cur) < len(sessions),
                            "actions": actions, "positions": len(wc), "spy": round(infoc["spy"], 4)})
    reports_out.reverse()

    return {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "data_through": sessions[-1].date().isoformat(),
        "latest_report": latest.date().isoformat(), "cap": cfg["cap"],
        "candidates": candidates,
        "allocation": {"rows": allocation, "spy": round(info1["spy"], 4), "scale": round(info1["scale"], 4),
                       "total_raw": round(info1["total_raw"], 4)},
        "lists": lists_out,
        "reports": reports_out,
    }


def _list_row(sid, rank, features, s, e, held, own_today, rows, latest, all_reports, sessions, panel, last_close,
              key_of, names, weights, held_by, list_name, filter_reading, trades_open=None) -> dict:
    """One name on a list: status (held / next in line / filtered out), since added, gain since."""
    if sid in held:
        status, reason = "held", None
    else:
        reading = filter_reading(e["filter"], latest, sid) if e["filter"] else None
        if reading:
            status, reason = "filtered", reading
        elif sid in own_today.index:
            status, reason = "next", f"#{int(own_today.loc[sid, 'rank'])} on {e['name']}, outside the top {s.slot[1]}"
        else:
            status, reason = "next", "not in the list's top slots"
    start = _streak_start(rows, sid, latest, all_reports)
    added = gain = days = None
    if start is None and sid in held and trades_open is not None:
        # Held from an earlier listing (a fixed hold still running) but off today's list: use the open trade.
        t = trades_open[(trades_open["strategy_id"] == s.id) & (trades_open["security_id"] == sid)]
        if not t.empty:
            t = t.sort_values("entry_date").iloc[0]
            added, gain = t["signal_date"].date().isoformat(), float(t["return_total"])
            days = int((sessions[-1] - t["entry_date"]).days)
            status, reason = "held", f"off the list; its {s.params.get('sessions')}-session hold is still running"
    if start is not None:
        e_idx = _sessions_index(sessions, start)
        if e_idx < len(sessions) and sid in panel.close.columns:
            entry = sessions[e_idx]
            px = fill_price(panel, entry, sid)
            gain = float(last_close.get(sid) / px - 1) if pd.notna(px) and pd.notna(last_close.get(sid)) else None
            days = int((sessions[-1] - entry).days)
        added = start.date().isoformat()
    others = [list_name[l] for l in held_by.get(sid, []) if l != s.id]
    return {"rank": rank, "key": key_of.get(sid, sid), "name": names.get(sid), "status": status, "reason": reason,
            "added": added, "days": days, "gain": None if gain is None else round(gain, 4),
            "feature": feature_text(features), "weight": round(weights.get(sid, 0.0), 4) if sid in held else None,
            "also_on": others}


def _exit_reason(s, e, sid, cur, by_cat, empty, filter_reading) -> str:
    if s.hold != "while_listed":
        return f"{s.params['sessions']}-session hold on {e['name']} ended"
    if e["filter"]:
        reading = filter_reading(e["filter"], cur, sid)
        if reading:
            return f"skipped by the {FILTER_LABEL[e['filter']]}: {reading}"
    rows = by_cat.get(e["base"] or s.category, empty)
    now = rows[(rows["report_date"] == cur) & (rows["security_id"] == sid)]
    return f"fell to #{int(now['rank'].iloc[0])} on {e['base_name'] or e['name']}" if not now.empty else f"no longer on {e['base_name'] or e['name']}"
