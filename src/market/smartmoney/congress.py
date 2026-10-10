"""Congress: follow-the-disclosure member scores and the buy / holdings signals, point-in-time.

Every number for a report date uses only disclosures public by its `as_of` session.

A *lot* is one disclosed purchase. It is entered at the close of the first session after its
disclosure date and closed at the close of the first session after the member's next sale
disclosure of the same security (a sale closes every open lot of that name — PTRs rarely say
which); until then it is still owned and marked at `as_of`.

A member is judged on what they held over the trailing window: lots bought inside it, plus lots
bought earlier and still owned when it began (no sale disclosed by then), which count from the
window's first session at their value then (disclosed amount × the stock's move to that point).
The score is the value-weighted average of each lot's return minus SPY's over the same sessions.
The ledger starts 2024-06-18, so holdings bought before it are unknown unless a later sale shows them.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from market.data.securities import map_tickers
from market.store.panel import Panel

WINDOW_DAYS = 730                 # trailing disclosures a member is judged on (smartmoney's window)
MIN_LOTS = 5                      # lots needed before a member can rank
TOP_MEMBERS = 5
BUY_WINDOW_DAYS = 120             # a purchase counts as "new" for this long (smartmoney dashboard)
SIGNAL_START = pd.Timestamp("2024-12-31")   # six months of disclosures before the first ranking


@dataclass
class CongressData:
    trades: pd.DataFrame          # every disclosed trade with a mapped security
    lots: pd.DataFrame            # purchases with entry / exit session positions
    close: np.ndarray             # sessions × securities, split-adjusted, forward-filled
    col: dict[str, int]           # security_id → column in `close`
    spy: np.ndarray
    sessions: pd.DatetimeIndex


def first_needed(frame: pd.DataFrame) -> dict[str, object]:
    """Ticker → first date its prices are needed (every purchased name, from its first buy)."""
    buys = frame[frame["tx_type"] == "P"]
    return {t: d.date() for t, d in buys.groupby("ticker")["disclosed"].min().items()}


def build(frame: pd.DataFrame, panel: Panel, history: pd.DataFrame, benchmark: str = "SPY") -> CongressData:
    trades = frame.copy()
    trades["security_id"] = map_tickers(history, trades["ticker"], trades["disclosed"])
    trades = trades.dropna(subset=["security_id"])
    sessions = panel.sessions
    # First session strictly after the disclosure date: PTRs post during and after market hours.
    trades["pos"] = sessions.searchsorted(trades["disclosed"].to_numpy(), side="right")

    buys = trades[trades["tx_type"] == "P"].reset_index(drop=True)
    sales = trades[trades["tx_type"] == "S"][["member_id", "security_id", "disclosed", "traded", "pos"]]
    pairs = buys.reset_index().merge(sales, on=["member_id", "security_id"], suffixes=("", "_sale"))
    later = pairs[(pairs["disclosed_sale"] > pairs["disclosed"])
                  | ((pairs["disclosed_sale"] == pairs["disclosed"]) & (pairs["traded_sale"] > pairs["traded"]))]
    exit_pos = later.groupby("index")["pos_sale"].min()
    exit_disclosed = later.groupby("index")["disclosed_sale"].min()
    buys["exit_pos"] = exit_pos.reindex(buys.index).fillna(np.iinfo(np.int32).max).astype(np.int64)
    buys["exit_disclosed"] = exit_disclosed.reindex(buys.index)

    ids = sorted(set(buys["security_id"]) & set(panel.close.columns))
    close = panel.close[ids].ffill(limit=10).to_numpy()
    col = {sid: i for i, sid in enumerate(ids)}
    buys = buys[buys["security_id"].isin(col)].reset_index(drop=True)
    buys["col"] = buys["security_id"].map(col).astype(int)
    spy = panel.close[_benchmark_id(panel, history, benchmark)].ffill().to_numpy()
    return CongressData(trades, buys, close, col, spy, sessions)


def _benchmark_id(panel: Panel, history: pd.DataFrame, ticker: str) -> str:
    rows = history[(history["ticker"] == ticker) & history["valid_to"].isna()]
    return rows["security_id"].iloc[0]


def lot_returns(data: CongressData, as_of_pos: int, window_days: int | None = None) -> pd.DataFrame:
    """Lots owned at some point in the trailing window and public by `as_of`: bought inside it, or
    bought earlier and not yet sold when it began (those start at the window's first session).
    Adds start (session position), carried, value (the weight: amount, grown to the window start
    for carried lots), ret and spy_ret to date, and open."""
    cutoff = data.sessions[as_of_pos] - pd.Timedelta(days=window_days or WINDOW_DAYS)
    cut_pos = int(data.sessions.searchsorted(cutoff, side="left"))
    lots = data.lots[(data.lots["pos"] <= as_of_pos) & (data.lots["exit_pos"] > cut_pos)].copy()
    entry = lots["pos"].to_numpy()
    start = np.maximum(entry, cut_pos)
    end = np.minimum(lots["exit_pos"].to_numpy(), as_of_pos)
    cols = lots["col"].to_numpy()
    p_entry, p0, p1 = data.close[entry, cols], data.close[start, cols], data.close[end, cols]
    lots["start"] = start
    lots["carried"] = entry < cut_pos
    lots["value"] = lots["amount"].fillna(1.0).to_numpy() * np.where(entry < cut_pos, p0 / p_entry, 1.0)
    lots["ret"] = p1 / p0 - 1
    lots["spy_ret"] = data.spy[end] / data.spy[start] - 1
    lots["open"] = lots["exit_pos"].to_numpy() > as_of_pos
    return lots.dropna(subset=["ret", "spy_ret", "value"])


def member_scores(data: CongressData, as_of_pos: int, window_days: int | None = None) -> pd.DataFrame:
    lots = lot_returns(data, as_of_pos, window_days)
    if lots.empty:
        return pd.DataFrame()
    lots["w"] = lots["value"]
    lots["wr"] = lots["w"] * lots["ret"]
    lots["wa"] = lots["w"] * (lots["ret"] - lots["spy_ret"])
    lots["win"] = (lots["ret"] > lots["spy_ret"]).astype(float)
    g = lots.groupby("member_id")
    scores = pd.DataFrame({
        "member": g["member"].last(),
        "chamber": g["chamber"].last(),
        "party": g["party"].last() if "party" in lots else None,
        "state": g["state"].last() if "state" in lots else None,
        "lots": g.size(),
        "open_lots": g["open"].sum(),
        "carried": g["carried"].sum(),
        "dollars": g["w"].sum(),
        "dw_return": g["wr"].sum() / g["w"].sum(),
        "dw_alpha": g["wa"].sum() / g["w"].sum(),
        "beat_spy": g["win"].mean(),
    })
    scores["rankable"] = scores["lots"] >= MIN_LOTS
    ranked = scores[scores["rankable"]].sort_values("dw_alpha", ascending=False)
    scores["rank"] = pd.Series(np.arange(1, len(ranked) + 1), index=ranked.index)
    return scores.sort_values(["rank", "dw_alpha"], ascending=[True, False])


def disclosure_totals(frame: pd.DataFrame, as_of: pd.Timestamp, window_days: int | None = None) -> pd.DataFrame:
    """Per member: every trade disclosed in the window (any asset, mapped or not) — count and the
    range-midpoint dollars of purchases and sales."""
    cutoff = as_of - pd.Timedelta(days=window_days or WINDOW_DAYS)
    t = frame[(frame["disclosed"] > cutoff) & (frame["disclosed"] <= as_of)]
    amt = t["amount"].fillna(0)
    g = pd.DataFrame({"member_id": t["member_id"], "buy": amt.where(t["tx_type"] == "P", 0),
                      "sell": amt.where(t["tx_type"] == "S", 0)}).groupby("member_id")
    return pd.DataFrame({"trades": g.size(), "bought": g["buy"].sum(), "sold": g["sell"].sum()})


def top_members(scores: pd.DataFrame, n: int = TOP_MEMBERS) -> pd.DataFrame:
    if scores.empty:
        return scores
    return scores[(scores["rank"] <= n) & (scores["dw_alpha"] > 0)]


def _member_list(group: pd.DataFrame) -> str:
    return ", ".join(sorted(group["member"].unique()))


def new_buys(data: CongressData, scores: pd.DataFrame, as_of_pos: int) -> pd.DataFrame:
    """Purchases by the top members disclosed in the last BUY_WINDOW_DAYS, by share of each
    member's recent buying (each member counts equally), summed across members."""
    top = top_members(scores)
    as_of = data.sessions[as_of_pos]
    recent = data.lots[(data.lots["pos"] <= as_of_pos)
                       & (data.lots["disclosed"] > as_of - pd.Timedelta(days=BUY_WINDOW_DAYS))
                       & data.lots["member_id"].isin(top.index)].copy()
    if recent.empty:
        return pd.DataFrame(columns=["score"])
    recent["w"] = recent["amount"].fillna(1.0)
    recent["share"] = recent["w"] / recent.groupby("member_id")["w"].transform("sum")
    g = recent.groupby("security_id")
    frame = pd.DataFrame({
        "score": g["share"].sum(),
        "dollars": g["w"].sum(),
        "buys": g.size().astype(float),
        "members": g.apply(_member_list, include_groups=False),
        "last_disclosed": g["disclosed"].max().dt.date.astype(str),
        "last_traded": g["traded"].max().dt.date.astype(str),
    })
    return frame.sort_values(["score", "dollars"], ascending=False)


def holdings(data: CongressData, scores: pd.DataFrame, as_of_pos: int) -> pd.DataFrame:
    """Names the top members still hold (bought within the window, no sale disclosed yet),
    by share of each member's open book, summed across members."""
    top = top_members(scores)
    lots = lot_returns(data, as_of_pos)
    held = lots[lots["open"] & lots["member_id"].isin(top.index)].copy()
    if held.empty:
        return pd.DataFrame(columns=["score"])
    held["w"] = held["value"]
    held["share"] = held["w"] / held.groupby("member_id")["w"].transform("sum")
    g = held.groupby("security_id")
    frame = pd.DataFrame({
        "score": g["share"].sum(),
        "dollars": g["w"].sum(),
        "lots": g.size().astype(float),
        "members": g.apply(_member_list, include_groups=False),
        "first_disclosed": g["disclosed"].min().dt.date.astype(str),
        "return_since": (g.apply(lambda x: np.average(x["ret"], weights=x["w"]), include_groups=False)),
    })
    return frame.sort_values(["score", "dollars"], ascending=False)


class CongressSignals:
    """Per-report cache so both categories and the export share one scoring pass per date."""

    def __init__(self, data: CongressData):
        self.data = data
        self._scores: dict[int, pd.DataFrame] = {}

    def pos(self, as_of: pd.Timestamp) -> int:
        return int(self.data.sessions.get_loc(as_of))

    def scores(self, as_of: pd.Timestamp) -> pd.DataFrame:
        p = self.pos(as_of)
        if p not in self._scores:
            self._scores[p] = member_scores(self.data, p)
        return self._scores[p]

    def new_buys(self, as_of: pd.Timestamp) -> pd.DataFrame:
        return new_buys(self.data, self.scores(as_of), self.pos(as_of))

    def holdings(self, as_of: pd.Timestamp) -> pd.DataFrame:
        return holdings(self.data, self.scores(as_of), self.pos(as_of))
