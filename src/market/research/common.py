"""Shared event-study helpers: forward returns vs SPY, bucket and threshold tables, report writing.

An event is (security_id, date): something known after the close of `date`. Its forward return
starts at the next session's close (a stand-in for the next-session VWAP fill the engine uses)
and runs `h` sessions on the total-return index, minus SPY over the same sessions.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from market.config import ROOT
from market.store.panel import Panel

HORIZONS = (5, 21, 63)


def spy_id(con) -> str:
    return con.execute("SELECT security_id FROM securities WHERE type = 'ETF' AND ticker = 'SPY'").fetchone()[0]


def forward_excess(panel: Panel, events: pd.DataFrame, bench_id: str, horizons=HORIZONS) -> pd.DataFrame:
    """Adds `ret_<h>` and `xs_<h>` (vs the benchmark) for each horizon; NaN where history runs out."""
    out = events.copy()
    sessions = panel.sessions
    pos = sessions.searchsorted(pd.to_datetime(out["date"]), side="right")      # first session after the event
    tr = panel.tr
    cols = tr.columns.get_indexer(out["security_id"])
    bench = tr[bench_id].to_numpy()
    values = tr.to_numpy()
    for h in horizons:
        ret = np.full(len(out), np.nan)
        xs = np.full(len(out), np.nan)
        ok = (cols >= 0) & (pos + h < len(sessions))
        i, j, k = pos[ok], cols[ok], pos[ok] + h
        r = values[k, j] / values[i, j] - 1
        b = bench[k] / bench[i] - 1
        ret[ok], xs[ok] = r, r - b
        out[f"ret_{h}"], out[f"xs_{h}"] = ret, xs
    return out


def split(frame: pd.DataFrame, cut: date, column: str = "date") -> tuple[pd.DataFrame, pd.DataFrame]:
    """(in-sample before `cut`, out-of-sample on/after it)."""
    when = pd.to_datetime(frame[column])
    return frame[when < pd.Timestamp(cut)], frame[when >= pd.Timestamp(cut)]


def summarize(returns: pd.Series) -> dict:
    r = returns.dropna()
    if r.empty:
        return {"n": 0, "mean": None, "median": None, "hit": None, "t": None}
    t = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 and r.std(ddof=1) > 0 else None
    return {"n": int(len(r)), "mean": float(r.mean()), "median": float(r.median()), "hit": float((r > 0).mean()), "t": t}


def bucket_table(frame: pd.DataFrame, feature: str, ret: str, buckets: int = 10) -> pd.DataFrame:
    """Mean / median / hit rate of `ret` by quantile bucket of `feature` (1 = lowest)."""
    f = frame[[feature, ret]].dropna()
    if len(f) < buckets * 5:
        return pd.DataFrame()
    f = f.assign(bucket=pd.qcut(f[feature].rank(method="first"), buckets, labels=range(1, buckets + 1)))
    rows = [{"bucket": int(b), "lo": float(g[feature].min()), "hi": float(g[feature].max()), **summarize(g[ret])}
            for b, g in f.groupby("bucket", observed=True)]
    return pd.DataFrame(rows)


def threshold_table(frame: pd.DataFrame, feature: str, ret: str, thresholds, above: bool = True) -> pd.DataFrame:
    """`ret` for events with feature ≥ (or ≤) each threshold, next to all events."""
    rows = [{"threshold": "all", **summarize(frame[ret])}]
    for th in thresholds:
        part = frame[frame[feature] >= th] if above else frame[frame[feature] <= th]
        rows.append({"threshold": f"{'≥' if above else '≤'} {th:g}", **summarize(part[ret])})
    return pd.DataFrame(rows)


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}" if abs(value) >= 1 else f"{value:.2%}" if abs(value) < 1 else str(value)
    return str(value)


def markdown_table(frame: pd.DataFrame, percent: tuple[str, ...] = ("mean", "median", "hit")) -> str:
    if frame.empty:
        return "_too few events_\n"
    head = "| " + " | ".join(frame.columns) + " |\n|" + "---|" * len(frame.columns) + "\n"
    body = ""
    for row in frame.itertuples(index=False):
        cells = []
        for col, value in zip(frame.columns, row):
            if col in percent and value is not None and not (isinstance(value, float) and np.isnan(value)):
                cells.append(f"{value:+.2%}" if col != "hit" else f"{value:.0%}")
            elif col == "t" and value is not None and not (isinstance(value, float) and np.isnan(value)):
                cells.append(f"{value:.1f}")
            else:
                cells.append(_fmt(value) if not isinstance(value, (int, np.integer)) else str(value))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def write_report(number: int, slug: str, title: str, markdown: str, payload: dict) -> Path:
    """docs/research/NN-slug.md (for reading) and data/research/slug.json (for code and the site)."""
    doc = ROOT / "docs" / "research" / f"{number:02d}-{slug}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"# {title}\n\n_Generated {date.today()} by `python -m market.research.{slug.replace('-', '_')}`._\n\n{markdown}")
    data = ROOT / "data" / "research" / f"{slug}.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(payload, default=str, indent=1))
    return doc


def decile_returns(obs: pd.DataFrame, feature: str, ret: str, deciles: int = 10) -> pd.DataFrame:
    """date × decile mean of `ret` (deciles formed within each date)."""
    f = obs[["date", feature, ret]].dropna()
    f = f[f.groupby("date")[feature].transform("size") >= deciles * 3]
    f["decile"] = f.groupby("date")[feature].transform(
        lambda x: pd.qcut(x.rank(method="first"), deciles, labels=False) + 1)
    return f.groupby(["date", "decile"])[ret].mean().unstack()


def spread(by_date: pd.DataFrame) -> dict:
    """Top minus bottom bucket, per date, summarized across dates."""
    s = (by_date[by_date.columns.max()] - by_date[1]).dropna()
    return summarize(s)


def members_frame(con) -> pd.DataFrame:
    """S&P 500 / 400 membership intervals with open ends filled (for point-in-time filters)."""
    m = con.execute("SELECT universe, security_id, valid_from, valid_to FROM universe_membership "
                    "WHERE universe IN ('sp500', 'sp400') AND security_id IS NOT NULL").df()
    m["valid_from"] = pd.to_datetime(m["valid_from"]).fillna(pd.Timestamp.min)
    m["valid_to"] = pd.to_datetime(m["valid_to"]).fillna(pd.Timestamp.max)
    return m


def universe_mean_excess(panel: Panel, members: pd.DataFrame, dates, bench: str, horizons=HORIZONS) -> pd.DataFrame:
    """date × horizon: the average S&P 500 / 400 member's excess return vs `bench` over the same window
    (starting the session after `date`) — the fair baseline for event lists, since an equal-weight list
    of mid caps lags cap-weighted SPY on its own."""
    tr = panel.tr
    values, b = tr.to_numpy(), tr[bench].to_numpy()
    out = {}
    for d in dates:
        live = members[(members["valid_from"] <= d) & (members["valid_to"] > d)]["security_id"].unique()
        cols = tr.columns.get_indexer(live)
        cols = cols[cols >= 0]
        i = panel.sessions.searchsorted(pd.Timestamp(d), side="right")
        out[d] = {h: (float(np.nanmean(values[i + h, cols] / values[i, cols] - 1) - (b[i + h] / b[i] - 1))
                      if i + h < len(panel.sessions) else np.nan) for h in horizons}
    return pd.DataFrame(out).T
