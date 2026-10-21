"""Site data for the Options page: per base strategy, every option method beside the stock
version over the same windows, plus what each method would open today for current holdings.

Today's picks use the latest session in the option panel (the previous session's flat file),
the same selection rule as the backtest.
"""

from __future__ import annotations

import pandas as pd

from market.data.options import option_root
from market.evaluate.options_engine import load_option_data
from market.evaluate.engine import OPTION_INSTRUMENTS
from market.methods.instruments.options import Book, _leap_pick, _short_pick


def _num(value, digits=6):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return round(float(value), digits)


def todays_picks(data, panel, base, methods, holdings: list[tuple[str, str]]) -> list[dict]:
    """holdings: (security_id, ticker). One row per holding × method."""
    if data is None or data.last_session is None:
        return []
    sel = data.last_session
    open_day = sel + pd.offsets.BDay(1)
    rows = []
    for sid, ticker in holdings:
        root = option_root(ticker)
        if sid not in data.raw_close.columns or pd.isna(data.raw_close.at[sel, sid]):
            continue
        spot = data.spot_close(sid, sel)
        for m in methods:
            inst = m["instrument"]
            book = Book(data, sid, root, m, 0.0)      # the backtest's own contract pickers
            picks = []
            if inst in ("leap", "diagonal"):
                picks.append(("long", _leap_pick(book, sel, open_day)))
            if inst in ("csp", "covered_call", "diagonal"):
                picks.append(("short", _short_pick(book, sel, open_day)))
            legs = []
            for side, pick in picks:
                if pick is None:
                    legs.append({"side": side, "missing": True})
                    continue
                _, expiry, kind, strike = pick["contract"]
                bar = data.bar(pick["contract"], sel)
                premium = float(bar["close"])
                dte = (expiry - open_day).days
                leg = {"side": side, "kind": kind, "expiry": expiry.date().isoformat(), "strike": strike, "dte": dte,
                       "premium": _num(premium, 2), "delta": _num(pick["delta"], 3), "iv": _num(pick["iv"], 3)}
                if side == "short" and kind == "P":
                    leg["yield_annual"] = _num(premium / strike * 365 / max(dte, 1), 4)
                    leg["breakeven_pct"] = _num((strike - premium) / spot - 1, 4)
                elif side == "short":
                    leg["yield_annual"] = _num(premium / spot * 365 / max(dte, 1), 4)
                    leg["cap_pct"] = _num(strike / spot - 1, 4)
                else:
                    leg["cost_pct"] = _num(premium / spot, 4)
                    leg["extrinsic_pct"] = _num((premium - max(spot - strike, 0)) / spot, 4)
                    sizing = m.get("sizing", "notional")
                    if sizing not in ("delta", "notional"):   # share of capital in calls → stock-equivalent exposure
                        leg["exposure"] = _num(float(sizing) * pick["delta"] * spot / premium, 3)
                    elif sizing == "delta":
                        leg["exposure"] = 1.0
                legs.append(leg)
            rows.append({"ticker": ticker, "spot": _num(spot, 2), "method": m["id"], "legs": legs})
    return rows


def _stock_same(metrics_by: dict, base_id: str, methods) -> dict:
    """The stock-over-same-windows metrics, plus its trade stats (half-Kelly, win rate) from the method stats."""
    out = {k: dict(v) for k, v in metrics_by.get(f"{base_id}.stock_same", {}).items()}
    extra = metrics_by.get(methods[0].id, {}).get("all", {}).get("stock_same", {})
    out.setdefault("all", {}).update({k: extra.get(k) for k in ("half_kelly", "win_rate", "stock_equiv", "position")})
    return out


def build(con, panel, strategies, metrics_by: dict, navs: pd.DataFrame, session_index: dict, key_of: dict,
          strategy_label) -> dict:
    option_strats = [s for s in strategies if s.instrument in OPTION_INSTRUMENTS and s.stage != "lab"]
    if not option_strats:
        return {}
    data = load_option_data(con, panel)
    first = con.execute("SELECT min(session) FROM option_coverage").fetchone()[0]
    bases = list(dict.fromkeys(s.base for s in option_strats))
    by_base = []
    for base_id in bases:
        base = next(s for s in strategies if s.id == base_id)
        methods = [s for s in option_strats if s.base == base_id]
        series_ids = [f"{base_id}.stock_same"] + [s.id for s in methods]
        frames = {sid: navs[navs["strategy_id"] == sid].set_index("date") for sid in series_ids}
        frames = {sid: f for sid, f in frames.items() if not f.empty}
        if not frames:
            continue
        dates = list(next(iter(frames.values())).index)
        spy = navs[navs["strategy_id"] == "bench.SPY"].set_index("date")["nav"].reindex(dates)
        series = {sid: [_num(v, 3) for v in f["nav"].reindex(dates)] for sid, f in frames.items()}
        series["SPY"] = [_num(100 * v / spy.iloc[0], 3) for v in spy]
        holdings = con.execute(
            "SELECT DISTINCT security_id, ticker FROM trades WHERE strategy_id = ? AND status = 'open' ORDER BY ticker",
            [base_id]).fetchall()
        by_base.append({
            "id": base_id, "name": strategy_label(base)["name"], "hold": strategy_label(base)["hold"],
            "category": base.category,
            "start": session_index.get(dates[0]), "series": series,
            "stock_same": _stock_same(metrics_by, base_id, methods),
            "methods": [{"id": s.id, "method": s.method["id"], "label": s.method["label"], "tier": s.method.get("tier"),
                         "instrument": s.instrument, "expiry": s.method.get("expiry"), "sizing": s.method.get("sizing"),
                         "metrics": metrics_by.get(s.id, {})} for s in methods],
            "holdings": [key_of.get(sid, t) for sid, t in holdings],
            "picks": todays_picks(data, panel, base, [s.method for s in methods], holdings),
            "picks_as_of": data.last_session.date().isoformat() if data is not None else None,
        })
    return {"first_session": str(first), "bases": by_base}
