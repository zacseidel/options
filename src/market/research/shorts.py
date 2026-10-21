"""Shorts: do the short-candidate lists make money short, lag the market, or hedge a long strategy?

Each candidate list becomes a basket of lots (name, entry session = the session after the signal is
known, fixed hold). The basket's daily return is the equal-weighted return of its open lots (total
return, so a short pays the dividends). Three ways to use it, net of a borrow fee:

  short      short the basket alone: rf on the proceeds − basket return − borrow
  pair       long SPY, short the basket (dollar-neutral)
  hedge      the best long strategy (S&P 500 Leaders, short-interest filter) + a 30% short in the basket

Borrow: 0.5% a year, 3% for the heavily shorted lists (days to cover in the top fifth), an assumption
(no borrow-rate data). In-sample before CUT, out-of-sample after.

Candidate lists (S&P 500 / 400 members, point-in-time):
  div_cuts        regular dividend cut ≥ 10% (announcement), hold 126
  weak_earnings   Weak Earnings Reactions (≤ −5% vs SPY, gap held, 2× volume), hold 42
  iv_warning      Option-Implied Risk list (IV far above realized vol), hold 21
  crowded         top tenth of days to cover each month, hold 21
  decliners       each week, the 10 worst 12-month returns per index whose rank is still worsening vs a
                  month ago and that close below the 200-day average, hold 21
  decliners_crowded   decliners also in the top fifth of days to cover
  decliners_weak      decliners in the bottom 40% of Fundamental Momentum

Usage:  python -m market.research.shorts
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from market.categories.fundamentals import fmom_score
from market.config import config
from market.data.dividend_signals import events as dividend_events
from market.data.dividend_signals import stored
from market.data.fundamental_metrics import Fundamentals
from market.research.common import members_frame, spy_id, write_report
from market.store.db import connect
from market.store.panel import load_panel

CUT = date(2025, 1, 1)
HEDGE = 0.30
BORROW = {"default": 0.005, "crowded": 0.03}
LONG = "mom12si_sp500.top5"


def _members_on(members: pd.DataFrame, d: pd.Timestamp) -> pd.DataFrame:
    return members[(members["valid_from"] <= d) & (members["valid_to"] > d)]


def _lots(panel, signals: pd.DataFrame, hold: int) -> pd.DataFrame:
    """signals: security_id, date (signal known after this session's close) → lots with entry / exit index."""
    pos = panel.sessions.searchsorted(pd.to_datetime(signals["date"]), side="right")
    lots = signals.assign(entry=pos, exit=np.minimum(pos + hold, len(panel.sessions) - 1))
    return lots[lots["entry"] < len(panel.sessions) - 1]


def basket_returns(panel, lots: pd.DataFrame) -> pd.Series:
    """Equal-weighted daily total return of the open lots (0 when none are open)."""
    rets = panel.tr.pct_change().fillna(0.0)
    cols = rets.columns.get_indexer(lots["security_id"])
    lots = lots[cols >= 0].assign(col=cols[cols >= 0])
    n = len(panel.sessions)
    total, count = np.zeros(n), np.zeros(n)
    values = rets.to_numpy()
    for e, x, c in zip(lots["entry"], lots["exit"], lots["col"]):
        # A lot earns from the session after entry through its exit session.
        total[e + 1: x + 1] += values[e + 1: x + 1, c]
        count[e + 1: x + 1] += 1
    out = np.divide(total, count, out=np.zeros(n), where=count > 0)
    return pd.Series(out, index=panel.sessions), pd.Series(count, index=panel.sessions)


def candidate_lists(con, panel, members) -> dict[str, tuple[pd.DataFrame, int, str]]:
    out = {}
    # Dividend cuts.
    div, splits = stored(con)
    ev = dividend_events(div, splits, pd.to_datetime(div["ex_date"]).min())
    cuts = ev[(ev["type"] == "cut") & (ev["change"] <= -0.10)].copy()
    cuts["date"] = pd.to_datetime(cuts["date"])
    cuts = cuts[[not _members_on(members, d)[lambda m: m["security_id"] == s].empty
                 for s, d in zip(cuts["security_id"], cuts["date"])]]
    out["div_cuts"] = (cuts[["security_id", "date"]], 126, "default")
    # Lists already stored as category snapshots: listed on report dates (as-of = the prior session).
    for name, cat, hold in (("weak_earnings", "pead_down_sp900", 42), ("iv_warning", "ivrich_sp900", 21)):
        s = con.execute("SELECT as_of AS date, security_id FROM category_snapshots WHERE category_id = ? "
                        "AND origin = 'backtest'", [cat]).df()
        if not s.empty:                  # both lists were dropped from the Lab on 2026-10-21; their reports remain
            out[name] = (s, hold, "default")
    # Monthly crowded list and weekly decliners.
    si = con.execute("SELECT security_id, settlement_date, days_to_cover, available FROM short_interest").df()
    si["settlement_date"], si["available"] = pd.to_datetime(si["settlement_date"]), pd.to_datetime(si["available"])
    si = si.sort_values("available")
    close = panel.close
    sma200 = close.rolling(200, min_periods=180).mean()
    fund = Fundamentals(con, panel)
    weeks = pd.Series(panel.sessions, index=panel.sessions).groupby(panel.sessions.to_period("W")).last()
    weeks = weeks[weeks >= panel.sessions[275]]
    months = set(pd.Series(weeks.values).groupby(pd.DatetimeIndex(weeks.values).to_period("M")).first())
    crowded_rows, decl, decl_crowd, decl_weak = [], [], [], []
    for d in weeks:
        i = panel.sessions.get_loc(d)
        known = si[si["available"] <= d].drop_duplicates("security_id", keep="last").set_index("security_id")
        known = known[(d - known["settlement_date"]).dt.days <= 45]
        live = _members_on(members, d)
        for universe in ("sp500", "sp400"):
            ids = live[live["universe"] == universe]["security_id"].unique()
            dtc_pct = known["days_to_cover"].reindex(ids).dropna().rank(pct=True)
            if d in months:
                crowded_rows += [(s, d) for s in dtc_pct[dtc_pct >= 0.9].index]
            now = (close.iloc[i] / close.iloc[i - 252] - 1).reindex(ids).dropna()
            then = (close.iloc[i - 21] / close.iloc[i - 273] - 1).reindex(ids).dropna()
            rank_now, rank_then = now.rank(), then.rank()          # 1 = worst
            worsening = rank_now <= rank_then.reindex(rank_now.index)
            below = close.iloc[i].reindex(rank_now.index) < sma200.iloc[i].reindex(rank_now.index)
            picks = rank_now[worsening & below].sort_values().head(10).index
            decl += [(s, d) for s in picks]
            decl_crowd += [(s, d) for s in picks if dtc_pct.get(s, 0) >= 0.8]
            fm = fmom_score(fund.on(d, list(ids)))
            decl_weak += [(s, d) for s in picks if fm.get(s, 1) < 0.4]
    frame = lambda rows: pd.DataFrame(rows, columns=["security_id", "date"])              # noqa: E731
    out["crowded"] = (frame(crowded_rows), 21, "crowded")
    out["decliners"] = (frame(decl), 21, "default")
    out["decliners_crowded"] = (frame(decl_crowd), 21, "crowded")
    out["decliners_weak"] = (frame(decl_weak), 21, "default")
    return out


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 60:
        return {"cagr": None, "sharpe": None, "worst": None}
    nav = (1 + r).cumprod()
    years = len(r) / 252
    rf = config()["evaluation"]["risk_free_rate"]
    log = np.log1p(r)
    sharpe = (log.mean() * 252 - rf) / (log.std() * np.sqrt(252)) if log.std() > 0 else None
    return {"cagr": float(nav.iloc[-1] ** (1 / years) - 1), "sharpe": None if sharpe is None else float(sharpe),
            "worst": float((nav / nav.cummax() - 1).min())}


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    panel = load_panel(con)
    members = members_frame(con)
    spy = spy_id(con)
    rf = config()["evaluation"]["risk_free_rate"] / 252
    spy_r = panel.tr[spy].pct_change().fillna(0.0)
    long_nav = con.execute("SELECT date, nav FROM nav_daily WHERE strategy_id = ? ORDER BY date", [LONG]).df()
    long_r = long_nav.set_index(pd.to_datetime(long_nav["date"]))["nav"].pct_change().reindex(panel.sessions)
    lists = candidate_lists(con, panel, members)
    con.close()
    cut = pd.Timestamp(CUT)
    fmt = lambda v: "—" if v is None else f"{v:+.1%}"                                    # noqa: E731
    sfmt = lambda v: "—" if v is None else f"{v:.2f}"                                     # noqa: E731
    long_start = long_r.first_valid_index()
    lines = ["Annual return / Sharpe / worst drop. `basket` is the long basket itself (what a short loses on); "
             "`short` = rf − basket − borrow; `pair` = SPY − basket − borrow; `hedge` = "
             f"{LONG} + {HEDGE:.0%} short (from {long_start.date()}).\n",
             "| List | lots | avg open | period | basket | SPY | short | pair | hedge | long alone |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    payload = {}
    for name, (signals, hold, borrow_key) in lists.items():
        lots = _lots(panel, signals, hold)
        basket, count = basket_returns(panel, lots)
        active = count > 0
        first = count[active].index.min()
        borrow = BORROW[borrow_key] / 252
        short = (rf - basket - borrow).where(active, rf)
        pair = (spy_r - basket - borrow).where(active, 0.0)
        hedge = long_r + HEDGE * short.where(active, rf) - HEDGE * rf * (~active)
        payload[name] = {}
        for label, lo, hi in (("all", first, None), ("before 2025", first, cut), ("2025 on", cut, None)):
            sl = lambda s: s.loc[lo: hi - pd.Timedelta(days=1)] if hi is not None else s.loc[lo:]   # noqa: E731
            row = {k: stats(sl(v)) for k, v in (("basket", basket.where(active)), ("spy", spy_r), ("short", short),
                                                 ("pair", pair), ("hedge", hedge.loc[long_start:]),
                                                 ("long", long_r.loc[long_start:]))}
            payload[name][label] = row
            cell = lambda k: f"{fmt(row[k]['cagr'])} / {sfmt(row[k]['sharpe'])} / {fmt(row[k]['worst'])}"  # noqa: E731
            lines.append(f"| {name if label == 'all' else ''} | {len(lots) if label == 'all' else ''} | "
                         f"{count[active].mean():.0f}" * (label == "all") + f" | {label} | {cell('basket')} | {cell('spy')} | "
                         f"{cell('short')} | {cell('pair')} | {cell('hedge')} | {cell('long')} |")
        print(f"  {name}: {len(lots)} lots from {first.date()}", flush=True)
    outcome = ("> **Outcome (2026-10-21).** In this rising market most candidate lists lagged SPY but still rose, so\n"
               "> shorting them lost money and hedging with them cut returns. Dividend cuts were the exception: kept as\n"
               "> the Lab strategies Dividend Cutters (short) and S&P 500 Leaders SI filter + 30% dividend-cut hedge.\n\n")
    print(write_report(9, "shorts", "Shorts: candidate lists as shorts, pairs and hedges", outcome + "\n".join(lines) + "\n",
                       payload))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
