"""Lead time to leadership: does a category find future momentum leaders before they lead?

For every category, an *entry* is a name's first report in the category's top 10 after at least one
report outside it. An entry **leads** if the name was not in the matching Leaders top 10 (S&P 500
Leaders for S&P 500 / all-market categories, S&P 400 Leaders for S&P 400 ones) on any report in the
prior 30 days and joins it within the next 365 days; the lead time is the days until it does.

Usage:  python -m market.research.lead_time      (also computed by every export for the site)
"""

from __future__ import annotations

import argparse

import pandas as pd

import market.categories.catalog  # noqa: F401  (registers categories)
from market.categories.registry import REGISTRY
from market.research.common import write_report
from market.store.db import connect

TOP = 10
LOOKBACK_DAYS = 30
HORIZON_DAYS = 365
LEADERS = {"sp400": "mom12_sp400"}
DEFAULT_LEADERS = "mom12_sp500"


def _top(con) -> pd.DataFrame:
    frame = con.execute(
        "SELECT category_id, report_date, security_id FROM category_snapshots "
        "WHERE origin = 'backtest' AND rank <= ?", [TOP]).df()
    frame["report_date"] = pd.to_datetime(frame["report_date"])
    return frame


def entries(top: pd.DataFrame, category_id: str) -> pd.DataFrame:
    """(security_id, report_date) of each fresh entry into the category's top 10."""
    frame = top[top["category_id"] == category_id]
    dates = sorted(frame["report_date"].unique())
    prev: set[str] = set()
    rows = []
    for d in dates:
        now = set(frame.loc[frame["report_date"] == d, "security_id"])
        rows.extend((sid, d) for sid in now - prev)
        prev = now
    return pd.DataFrame(rows, columns=["security_id", "report_date"])


def lead_stats(entry_frame: pd.DataFrame, leaders: pd.DataFrame) -> dict | None:
    if entry_frame.empty or leaders.empty:
        return None
    by_sid = {sid: g["report_date"].sort_values().to_numpy() for sid, g in leaders.groupby("security_id")}
    last_leader_date = leaders["report_date"].max()
    already = leads = 0
    days = []
    eligible = 0
    for sid, d in entry_frame.itertuples(index=False):
        if d + pd.Timedelta(days=HORIZON_DAYS) > last_leader_date:
            continue                                   # outcome not known yet
        eligible += 1
        hits = by_sid.get(sid)
        if hits is None:
            continue
        hits = pd.to_datetime(hits)
        if ((hits >= d - pd.Timedelta(days=LOOKBACK_DAYS)) & (hits <= d)).any():
            already += 1
            continue
        later = hits[(hits > d) & (hits <= d + pd.Timedelta(days=HORIZON_DAYS))]
        if len(later):
            leads += 1
            days.append((later[0] - d).days)
    if not eligible:
        return None
    return {"entries": eligible, "already_leader": round(already / eligible, 4),
            "became_leader": round(leads / eligible, 4),
            "median_lead_days": int(pd.Series(days).median()) if days else None}


def compute(con) -> dict[str, dict]:
    top = _top(con)
    out = {}
    for cat_id, cat in REGISTRY.items():
        leader_id = LEADERS.get(cat.universe, DEFAULT_LEADERS)
        if cat_id == leader_id:
            continue
        stats = lead_stats(entries(top, cat_id), top[top["category_id"] == leader_id])
        if stats:
            out[cat_id] = {**stats, "leaders": leader_id}
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    con = connect()
    stats = compute(con)
    con.close()
    lines = ["Entries are a name's first report in a category's top 10. An entry *leads* if the name was not a Leaders "
             f"top-10 name in the prior {LOOKBACK_DAYS} days and joins within {HORIZON_DAYS} days.\n",
             "| Category | vs | Entries | Already leader | Became leader | Median lead (days) |", "|---|---|---|---|---|---|"]
    for cat_id, s in sorted(stats.items(), key=lambda kv: -kv[1]["became_leader"]):
        lines.append(f"| {REGISTRY[cat_id].name} | {REGISTRY[s['leaders']].name} | {s['entries']} | "
                     f"{s['already_leader']:.0%} | {s['became_leader']:.0%} | {s['median_lead_days'] or '—'} |")
    path = write_report(0, "lead-time", "Lead time to leadership", "\n".join(lines) + "\n", stats)
    print(path)


if __name__ == "__main__":
    main()
