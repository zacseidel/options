"""Best variant per strategy, and which strategies the Newsfeed follows (docs/PLAN-site.md §3).

  * **Variants are compared on common dates:** each eligible variant's Sharpe over the dates every eligible variant
    of the strategy has (so a filter with two years of history is judged against its base over those two years).
  * **Champion:** the highest of those Sharpes. A non-base variant must beat the base by `champion_tie`, otherwise
    the simpler base wins.
  * **Feed:** a champion enters when its since-inception Sharpe is at least `margin_in` × SPY's over the same dates
    (`benchmark_sharpe`, stored with every metrics row) and leaves when it falls below `margin_out` × (hysteresis,
    kept in `feed_state`). It also needs a positive half-Kelly (≥ 20 closed trades) to be sized.

Eligible variants: stock strategies the feed can hold — top slot (ranks 1…n) or every signal, held while listed or
for a fixed number of sessions. Ranks 6–10, price-exit, short and overlay strategies are shown but never champions.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from market.categories.families import FAMILIES, variant
from market.config import config
from market.evaluate.metrics import performance

HOLDS = ("while_listed", "fixed_hold")


def eligible(strategy) -> bool:
    top = strategy.slot == "all" or strategy.slot[0] == 1
    return strategy.instrument == "stock" and strategy.hold in HOLDS and top and strategy.stage != "retired"


def threshold(spy_sharpe: float, margin: float) -> float:
    """margin × SPY's Sharpe, measured as a distance from it so a negative SPY Sharpe still means 'beat it'."""
    return spy_sharpe + (margin - 1) * abs(spy_sharpe)


def compute(con, strategies, metrics: dict[str, dict], navs: pd.DataFrame) -> dict[str, dict]:
    """family id → {champion, variants: [{id, common_sharpe, …}], common_start, ratio, qualifies_in, qualifies_out}.
    `metrics`: strategy id → its 'all' window metrics; `navs`: date × strategy id."""
    cfg = config()["newsfeed"]
    rf = config()["evaluation"]["risk_free_rate"]
    out = {}
    for fam in FAMILIES.values():
        members = [s for s in strategies if variant(s.category).family == fam.id and s.stage != "retired"
                   and s.instrument not in ("csp", "covered_call", "leap", "diagonal") and s.id in navs]
        if not members:
            continue
        candidates = [s for s in members if eligible(s)]
        rows = {s.id: {"id": s.id, "category": s.category, "eligible": s in candidates} for s in members}
        champion = None
        common_start = None
        if candidates:
            common_start = max(navs[s.id].dropna().index[0] for s in candidates)
            for s in candidates:
                rows[s.id]["common_sharpe"] = performance(navs[s.id].dropna().loc[common_start:], rf).get("sharpe")
            scored = [s for s in candidates if rows[s.id].get("common_sharpe") is not None]
            if scored:
                best = max(scored, key=lambda s: rows[s.id]["common_sharpe"])
                base = next((s for s in scored if s.category == fam.base and s.slot != "all" and s.slot[0] == 1), None)
                if base and best is not base and rows[best.id]["common_sharpe"] - rows[base.id]["common_sharpe"] < cfg["champion_tie"]:
                    best = base
                champion = best
        info = {"family": fam.id, "variants": list(rows.values()), "champion": champion.id if champion else None,
                "common_start": common_start.date().isoformat() if common_start is not None else None}
        if champion:
            m = metrics.get(champion.id, {})
            sharpe, spy = m.get("sharpe"), m.get("benchmark_sharpe")
            sized = (m.get("half_kelly") or 0) > 0
            if sharpe is not None and spy is not None:
                info.update({"sharpe": sharpe, "spy_sharpe": spy, "ratio": sharpe / spy if spy > 0 else None,
                             "qualifies_in": sized and sharpe >= threshold(spy, cfg["margin_in"]),
                             "qualifies_out": sized and sharpe >= threshold(spy, cfg["margin_out"]),
                             "sized": sized})
        out[fam.id] = info
    return out


def update_feed(con, families: dict[str, dict], today: date | None = None) -> dict[str, dict]:
    """Apply the hysteresis against `feed_state` and store the new state. Adds in_feed / since to each family."""
    today = today or date.today()
    prior = {r[0]: {"champion": r[1], "in_feed": r[2], "since": r[3]}
             for r in con.execute("SELECT family_id, champion, in_feed, since FROM feed_state").fetchall()}
    for fid, info in families.items():
        was = prior.get(fid, {}).get("in_feed", False)
        now = bool(info.get("qualifies_out") if was else info.get("qualifies_in"))
        since = prior[fid]["since"] if was and now and prior.get(fid, {}).get("since") else (today if now else None)
        info.update({"in_feed": now, "since": since.isoformat() if isinstance(since, date) else since})
        con.execute("INSERT OR REPLACE INTO feed_state VALUES (?, ?, ?, ?, ?)",
                    [fid, info.get("champion"), now, since, datetime.now()])
    return families


def load_inputs(con, strategies) -> tuple[dict, pd.DataFrame]:
    metrics = {sid: json.loads(js) for sid, js in con.execute(
        "SELECT strategy_id, metrics FROM strategy_metrics WHERE window_name = 'all'").fetchall()}
    navs = con.execute("SELECT strategy_id, date, nav FROM nav_daily").df()
    navs["date"] = pd.to_datetime(navs["date"])
    return metrics, navs.pivot(index="date", columns="strategy_id", values="nav")
