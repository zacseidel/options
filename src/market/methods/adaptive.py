"""Adaptive option method: pick a base's option method per window from implied volatility (PLAN-signals §4).

On each window's selection session (the session before entry, the same day contracts are chosen),
the underlying's 30-day implied vol ÷ 20-day realized vol (`market.data.option_flow`) decides:

  * options rich  (iv_rv ≥ `rich`)  → `when_rich`  — sell premium (the base's cash-secured put)
  * options cheap (iv_rv ≤ `cheap`) → `when_cheap` — buy convexity (the base's long calls)
  * otherwise, or no reading         → `otherwise` — the base's Balanced method

The three branches are the base's own tracked methods, so the Adaptive tier only adds the choice.
`signal: pct` uses the name's percentile among liquid names that day instead of the raw ratio.
"""

from __future__ import annotations

import pandas as pd

from market.data.option_flow import feature_panel

BRANCHES = ("when_rich", "when_cheap", "otherwise")


class IvSignal:
    """iv_rv by session × security, and its cross-sectional percentile among liquid names."""

    def __init__(self, con, panel):
        fp = feature_panel(con, panel)
        fp = fp[fp["liquid"].fillna(False).astype(bool)]
        self.ratio = fp.pivot(index="date", columns="security_id", values="iv_rv")
        self.pct = self.ratio.rank(axis=1, pct=True)
        self.sessions = panel.sessions

    def at(self, security_id: str, entry: pd.Timestamp, kind: str = "ratio") -> float | None:
        """The reading on the session before `entry` (known when the contracts are chosen)."""
        pos = self.sessions.searchsorted(entry) - 1
        if pos < 0:
            return None
        day = self.sessions[pos]
        table = self.pct if kind == "pct" else self.ratio
        if day not in table.index or security_id not in table.columns:
            return None
        value = table.at[day, security_id]
        return None if pd.isna(value) else float(value)


def branch(method: dict, value: float | None) -> str:
    if value is None:
        return "otherwise"
    if value >= method["rich"]:
        return "when_rich"
    if value <= method["cheap"]:
        return "when_cheap"
    return "otherwise"
