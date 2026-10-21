"""Newsfeed (site #/news): what a portfolio following the configured strategies would do at each report.

For every report date (newest first, the upcoming one included when it is ready the evening before):

  1. each followed strategy's holdings — hold-while-listed: the names in its slot, equal weight;
     fixed hold: its open lots (one per listing, held N sessions), equal weight per lot;
  2. the portfolio's target weight per stock = Σ strategy weight × the stock's weight inside it, so a stock
     several strategies hold is one position, and one strategy selling while another buys nets out;
  3. the action per stock vs the previous report: Buy (new), Add, Trim, Sell (gone), Hold — with each
     strategy's reason (list and rank, or the hold ending) and, for positions a strategy closes, how that
     trade did against SPY over the same days.

The payload is encrypted with NEWSFEED_PASSWORD (.env) when it is set: AES-256-GCM with a key from
PBKDF2-SHA256, decrypted in the browser with WebCrypto. Without it the file is written in the clear.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime

import pandas as pd

from market.categories.registry import REGISTRY
from market.config import config, secret
from market.evaluate.engine import load_strategies
from market.reports.snapshot import upcoming_report

PBKDF2_ITERATIONS = 250_000
HOLDS = ("while_listed", "fixed_hold")


def _pct(v, signed=True) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:+.0f}%" if signed else f"{v * 100:.0f}%"


def feature_text(features: dict) -> str:
    """One short phrase from a list row's features, for the 'why' column."""
    f = features or {}
    if f.get("return_12m") is not None:
        return f"12-month return {_pct(f['return_12m'])}"
    if f.get("avg_rank") is not None:
        return f"average rank {f['avg_rank']:.1f}"
    if f.get("longevity") is not None:
        return f"{round(f['longevity'] * 26)}/26 weeks in the top 50"
    if f.get("gross_margin_chg") is not None:
        return f"gross margin {f['gross_margin_chg'] * 100:+.1f} pts, op. margin {(f.get('op_margin_chg') or 0) * 100:+.1f} pts"
    if f.get("fmom") is not None:
        return f"fundamental score {f['fmom']:.2f}"
    if f.get("raise") is not None:
        return f"dividend raised {_pct(f['raise'])}"
    if f.get("return_3m") is not None:
        return f"3-month return {_pct(f['return_3m'])}"
    return ""


def _sessions_index(sessions: pd.DatetimeIndex, d) -> int:
    """Index of the session on/after `d` (len(sessions) for a date after the last stored session)."""
    return int(sessions.searchsorted(pd.Timestamp(d)))


def holdings(strategy, snaps: pd.DataFrame, report: pd.Timestamp, sessions: pd.DatetimeIndex) -> dict:
    """security_id → {weight, rows}: what the strategy holds after acting on `report`."""
    slot = strategy.slot
    rows = snaps if slot == "all" else snaps[snaps["rank"].between(slot[0], slot[1])]
    out: dict[str, dict] = {}
    if strategy.hold == "while_listed":
        today = rows[rows["report_date"] == report]
        for r in today.itertuples(index=False):
            out[r.security_id] = {"lots": 1, "row": r}
    else:
        n = strategy.params["sessions"]
        idx = _sessions_index(sessions, report)
        past = rows[rows["report_date"] <= report]
        for r in past.itertuples(index=False):
            e = _sessions_index(sessions, r.report_date)
            if e <= idx < e + n:
                cur = out.setdefault(r.security_id, {"lots": 0, "row": r})
                cur["lots"] += 1
                cur["row"] = r
    total = sum(v["lots"] for v in out.values())
    for v in out.values():
        v["weight"] = v["lots"] / total
    return out


def build(con, panel, key_of: dict) -> dict:
    cfg = config()["newsfeed"]
    by_id = {s.id: s for s in load_strategies()}
    followed = [(by_id[p["strategy"]], p["weight"]) for p in cfg["portfolio"] if p["strategy"] in by_id]
    followed = [(s, w) for s, w in followed if s.hold in HOLDS and s.instrument == "stock"]
    total_w = sum(w for _, w in followed)
    followed = [(s, w / total_w) for s, w in followed]
    sessions = panel.sessions
    cats = sorted({s.category for s, _ in followed})
    snaps = con.execute(f"SELECT category_id, report_date, as_of, security_id, ticker, rank, features "
                        f"FROM category_snapshots WHERE origin = 'backtest' AND category_id IN "
                        f"({','.join('?' * len(cats))})", cats).df()
    snaps["report_date"] = pd.to_datetime(snaps["report_date"])
    snaps["features"] = snaps["features"].map(json.loads)
    by_cat = {c: g for c, g in snaps.groupby("category_id")}
    trades = con.execute("SELECT strategy_id, security_id, signal_date, entry_date, exit_signal_date, exit_date, "
                         "return_total, status FROM trades WHERE strategy_id IN "
                         f"({','.join('?' * len(followed))})", [s.id for s, _ in followed]).df()
    for col in ("signal_date", "entry_date", "exit_signal_date", "exit_date"):
        trades[col] = pd.to_datetime(trades[col])
    spy_id = con.execute("SELECT security_id FROM securities WHERE type = 'ETF' AND ticker = 'SPY'").fetchone()[0]
    spy = panel.tr[spy_id]
    names = dict(con.execute("SELECT security_id, name FROM securities").fetchall())

    upcoming = upcoming_report(panel)
    all_reports = sorted(d for d in snaps["report_date"].unique() if d.weekday() in (1, 4))
    shown = all_reports[-(cfg["reports"] + 1):]

    def spy_return(start, end) -> float | None:
        a = spy.loc[:start].dropna()
        b = spy.loc[:end].dropna()
        if a.empty or b.empty:
            return None
        before = spy.loc[:start - pd.Timedelta(days=1)].dropna()
        base = before.iloc[-1] if not before.empty else a.iloc[-1]
        return float(b.iloc[-1] / base - 1)

    def exit_result(strategy, sid, report, held_row) -> dict | None:
        t = trades[(trades["strategy_id"] == strategy.id) & (trades["security_id"] == sid)]
        if strategy.hold == "while_listed":
            t = t[t["exit_signal_date"] == report]
        else:
            t = t[t["signal_date"] == held_row.report_date]
        if t.empty:
            return None
        t = t.sort_values("entry_date").iloc[-1]
        end = t["exit_date"] if pd.notna(t["exit_date"]) else sessions[-1]
        return {"entry": t["entry_date"].date().isoformat(), "exit": end.date().isoformat(),
                "pending": t["status"] == "open", "return": round(float(t["return_total"]), 4),
                "spy": spy_return(t["entry_date"], end), "days": int((end - t["entry_date"]).days)}

    def portfolio(report) -> tuple[dict, dict]:
        weights, per = {}, {}
        for s, w in followed:
            h = holdings(s, by_cat.get(s.category, snaps.iloc[0:0]), report, sessions)
            per[s.id] = h
            for sid, v in h.items():
                weights[sid] = weights.get(sid, 0.0) + w * v["weight"]
        return weights, per

    states = {d: portfolio(d) for d in shown}
    reports_out = []
    for prev, cur in zip(shown[:-1], shown[1:]):
        (w0, p0), (w1, p1) = states[prev], states[cur]
        actions = []
        for sid in sorted(set(w0) | set(w1)):
            a, b = w0.get(sid, 0.0), w1.get(sid, 0.0)
            ins, outs = [], []
            for s, sw in followed:
                h0, h1 = p0[s.id].get(sid), p1[s.id].get(sid)
                label = REGISTRY[s.category].name
                if h1 and (not h0 or h1["lots"] > h0["lots"]):
                    r = h1["row"]
                    why = f"#{int(r.rank)} on {label}" if s.slot != "all" else f"listed on {label}"
                    ft = feature_text(r.features)
                    ins.append({"strategy": s.id, "label": label, "why": why + (f" — {ft}" if ft else "")})
                if h0 and (not h1 or h1["lots"] < h0["lots"]):
                    if s.hold == "while_listed":
                        now = by_cat.get(s.category, snaps.iloc[0:0])
                        now = now[(now["report_date"] == cur) & (now["security_id"] == sid)]
                        why = (f"fell to #{int(now['rank'].iloc[0])} on {label}" if not now.empty
                               else f"no longer on {label}")
                    else:
                        why = f"{s.params['sessions']}-session hold on {label} ended"
                    outs.append({"strategy": s.id, "label": label, "why": why,
                                 "result": exit_result(s, sid, cur, h0["row"])})
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
            actions.append({"key": key_of.get(sid, sid), "name": names.get(sid), "action": action,
                            "before": round(a, 4), "after": round(b, 4), "in": ins, "out": outs})
        order = {"Buy": 0, "Add": 1, "Trim": 2, "Sell": 3, "Hold": 4}
        actions.sort(key=lambda x: (order[x["action"]], -x["after"], x["key"]))
        held = sorted(((key_of.get(sid, sid), round(w, 4)) for sid, w in w1.items()), key=lambda x: -x[1])
        as_of = sessions[min(_sessions_index(sessions, cur), len(sessions)) - 1].date().isoformat()
        reports_out.append({"date": cur.date().isoformat(), "as_of": as_of,
                            "upcoming": upcoming is not None and cur.date() == upcoming,
                            "filled": _sessions_index(sessions, cur) < len(sessions),
                            "actions": actions, "holding": held})
    reports_out.reverse()

    latest_w, latest_p = states[shown[-1]]
    current = []
    for sid, w in sorted(latest_w.items(), key=lambda kv: -kv[1]):
        open_t = trades[(trades["security_id"] == sid) & (trades["status"] == "open")]
        current.append({"key": key_of.get(sid, sid), "name": names.get(sid), "weight": round(w, 4),
                        "strategies": [REGISTRY[s.category].name for s, _ in followed if sid in latest_p[s.id]],
                        "since": open_t["entry_date"].min().date().isoformat() if not open_t.empty else None,
                        "return": round(float(open_t["return_total"].mean()), 4) if not open_t.empty else None})
    return {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "data_through": sessions[-1].date().isoformat(),
        "portfolio": [{"id": s.id, "name": REGISTRY[s.category].name, "slot": s.slot if s.slot == "all" else
                       f"top {s.slot[1]}" if s.slot[0] == 1 else f"ranks {s.slot[0]}–{s.slot[1]}",
                       "hold": s.hold, "sessions": s.params.get("sessions"), "weight": round(w, 4),
                       "stage": s.stage} for s, w in followed],
        "current": current,
        "reports": reports_out,
    }


def seal(payload: dict, password: str | None) -> dict:
    """Encrypt the payload for the browser (AES-256-GCM, PBKDF2-SHA256 key), or wrap it in the clear."""
    if not password:
        return {"encrypted": False, "data": payload}
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":"), default=str).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()                                          # noqa: E731
    return {"encrypted": True, "kdf": "PBKDF2-SHA256", "iterations": PBKDF2_ITERATIONS,
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def export(con, panel, key_of: dict) -> dict:
    return seal(build(con, panel, key_of), secret("NEWSFEED_PASSWORD", required=False))
