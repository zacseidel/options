"""Point-in-time fundamentals: XBRL facts → quarterly values → per-filing company state.

1. `quarterly(facts)`: one row per company per fiscal quarter, each value **as first filed**
   (restatements are ignored, so nothing is known before it was public). Flow metrics come from
   3-month facts, or by differencing year-to-date facts that share a start (6M − 3M, 9M − 6M,
   FY − 9M gives Q4, which 10-Ks don't report on their own). Balance-sheet values are as of the
   quarter end.
2. `states(quarters)`: the derived metrics (TTM, YoY growth, acceleration, margins and their
   change, free cash flow, share-count change, growth consistency) after each quarter is filed,
   usable from the day after its filing date (`effective`).

Market-cap multiples need a price, so they are computed when a state is read: market cap = diluted
shares × the unadjusted close at the quarter end, carried to the read date with the split-adjusted
price change (so a later split doesn't distort it). Works for S&P 400 names too, which have no
stored market caps.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FLOW = ["revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income", "ocf", "capex",
        "buybacks", "dividends"]
AVERAGE = ["diluted_shares"]          # duration facts that can't be differenced (weighted averages)
INSTANT = ["shares_out", "equity", "assets", "debt", "cash"]
QUARTER_DAYS = (80, 100)
YEAR_GAP = (350, 380)                 # a quarter and the same quarter a year earlier


def _first_filed(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per period, the preferred tag, then its first filing."""
    return frame.sort_values(["priority", "filed"]).drop_duplicates(keys, keep="first")


def _flow_quarters(facts: pd.DataFrame) -> pd.DataFrame:
    f = _first_filed(facts, ["cik", "metric", "start", "end"]).copy()
    f["days"] = (pd.to_datetime(f["end"]) - pd.to_datetime(f["start"])).dt.days
    direct = f[f["days"].between(*QUARTER_DAYS)][["cik", "metric", "end", "value", "filed"]]
    # Year-to-date differencing: a longer fact minus the fact with the same start ending ~a quarter earlier.
    longer = f[f["days"] > QUARTER_DAYS[1]]
    shorter = f[f["days"] >= QUARTER_DAYS[0]]
    pairs = longer.merge(shorter, on=["cik", "metric", "start"], suffixes=("", "_s"))
    gap = pairs["days"] - pairs["days_s"]
    pairs = pairs[gap.between(*QUARTER_DAYS)]
    derived = pd.DataFrame({"cik": pairs["cik"], "metric": pairs["metric"], "end": pairs["end"],
                            "value": pairs["value"] - pairs["value_s"],
                            "filed": pairs[["filed", "filed_s"]].max(axis=1)})
    # Q4 when there is no 9-month fact: the fiscal year minus its three reported quarters.
    years = f[f["days"].between(*YEAR_GAP)]
    q = f[f["days"].between(*QUARTER_DAYS)]
    inside = years.merge(q, on=["cik", "metric"], suffixes=("", "_q"))
    inside = inside[(inside["start_q"] >= inside["start"]) & (inside["end_q"] < inside["end"])]
    sums = inside.groupby(["cik", "metric", "start", "end"]).agg(
        value=("value", "first"), filed=("filed", "first"), q_sum=("value_q", "sum"), n=("value_q", "size")).reset_index()
    sums = sums[sums["n"] == 3]
    q4 = pd.DataFrame({"cik": sums["cik"], "metric": sums["metric"], "end": sums["end"],
                       "value": sums["value"] - sums["q_sum"], "filed": sums["filed"]})
    both = pd.concat([direct.assign(_direct=1), derived.assign(_direct=0), q4.assign(_direct=0)])
    # Prefer the earliest-known value for a quarter; a direct 3-month fact wins a tie.
    both = both.sort_values(["filed", "_direct"], ascending=[True, False])
    return both.drop_duplicates(["cik", "metric", "end"]).drop(columns="_direct")


def _average_quarters(facts: pd.DataFrame) -> pd.DataFrame:
    f = _first_filed(facts, ["cik", "metric", "start", "end"]).copy()
    days = (pd.to_datetime(f["end"]) - pd.to_datetime(f["start"])).dt.days
    # 3-month averages where reported; the fiscal-year average stands in for Q4.
    f = f[days.between(*QUARTER_DAYS) | days.between(*YEAR_GAP)].assign(_q=days.between(*QUARTER_DAYS))
    f = f.sort_values(["_q", "filed"], ascending=[False, True]).drop_duplicates(["cik", "metric", "end"])
    return f[["cik", "metric", "end", "value", "filed"]]


def _instant(facts: pd.DataFrame) -> pd.DataFrame:
    return _first_filed(facts, ["cik", "metric", "end"])[["cik", "metric", "end", "value", "filed"]]


def quarterly(facts: pd.DataFrame) -> pd.DataFrame:
    """cik, end, filed (when the quarter's revenue / income was first public), one column per metric."""
    facts = facts.copy()
    facts["end"] = pd.to_datetime(facts["end"])
    facts["start"] = pd.to_datetime(facts["start"])
    facts["filed"] = pd.to_datetime(facts["filed"])
    flow = _flow_quarters(facts[facts["metric"].isin(FLOW)])
    avg = _average_quarters(facts[facts["metric"].isin(AVERAGE)])
    # Only quarter ends that have a flow value define a quarter.
    ends = flow[["cik", "end"]].drop_duplicates()
    inst = _instant(facts[facts["metric"].isin(INSTANT)])
    inst = ends.merge(inst, on=["cik", "end"])          # balance sheet at the quarter end
    long = pd.concat([flow, ends.merge(avg, on=["cik", "end"]), inst])
    values = long.pivot_table(index=["cik", "end"], columns="metric", values="value", aggfunc="first")
    key = flow[flow["metric"].isin(["revenue", "net_income"])].groupby(["cik", "end"])["filed"].min()
    out = values.join(key.rename("filed"), how="inner").reset_index()
    for col in FLOW + AVERAGE + INSTANT:
        if col not in out:
            out[col] = np.nan
    gp_missing = out["gross_profit"].isna() & out["revenue"].notna() & out["cost_of_revenue"].notna()
    out.loc[gp_missing, "gross_profit"] = out["revenue"] - out["cost_of_revenue"]
    return out.sort_values(["cik", "end"]).reset_index(drop=True)


def _same_quarter_last_year(g: pd.DataFrame, lag: int) -> pd.Series:
    gap = (g["end"] - g["end"].shift(lag)).dt.days
    return gap.between(YEAR_GAP[0] * lag / 4, YEAR_GAP[1] * lag / 4)


def _growth(now: pd.Series, before: pd.Series) -> pd.Series:
    """Growth vs a positive base; NaN when the base is zero or negative (losses don't 'grow')."""
    return (now / before - 1).where(before > 0)


def _company_states(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("end").reset_index(drop=True)
    ok4 = (g["end"] - g["end"].shift(3)).dt.days.between(250, 300)     # 4 consecutive quarters
    year = _same_quarter_last_year(g, 4)
    ttm = lambda col: g[col].rolling(4, min_periods=4).sum().where(ok4)                     # noqa: E731
    out = pd.DataFrame({"cik": g["cik"], "end": g["end"], "filed": g["filed"]})
    for col in ("revenue", "gross_profit", "operating_income", "net_income", "ocf", "capex", "buybacks", "dividends"):
        out[f"{col}_ttm"] = ttm(col)
    out["fcf_ttm"] = out["ocf_ttm"] - out["capex_ttm"].fillna(0)
    out["rev_yoy_q"] = _growth(g["revenue"], g["revenue"].shift(4)).where(year)
    out["rev_accel"] = out["rev_yoy_q"] - out["rev_yoy_q"].shift(1)
    out["rev_ttm_yoy"] = _growth(out["revenue_ttm"], out["revenue_ttm"].shift(4)).where(year)
    out["ni_ttm_yoy"] = _growth(out["net_income_ttm"], out["net_income_ttm"].shift(4)).where(year)
    eps = g["net_income"] / g["diluted_shares"]
    out["eps_yoy_q"] = _growth(eps, eps.shift(4)).where(year)
    out["eps_accel"] = out["eps_yoy_q"] - out["eps_yoy_q"].shift(1)
    out["eps_ttm"] = out["net_income_ttm"] / g["diluted_shares"]
    # Standardized unexpected earnings / revenue (seasonal random walk): the change vs the same quarter
    # a year earlier, divided by the volatility of that change over the previous 8 quarters.
    eps_diff = (eps - eps.shift(4)).where(year)
    out["sue"] = eps_diff / eps_diff.shift(1).rolling(8, min_periods=4).std()
    rev_diff = (g["revenue"] - g["revenue"].shift(4)).where(year)
    out["rev_sue"] = rev_diff / rev_diff.shift(1).rolling(8, min_periods=4).std()
    out["gross_margin"] = out["gross_profit_ttm"] / out["revenue_ttm"]
    out["op_margin"] = out["operating_income_ttm"] / out["revenue_ttm"]
    out["fcf_margin"] = out["fcf_ttm"] / out["revenue_ttm"]
    out["gross_margin_chg"] = (out["gross_margin"] - out["gross_margin"].shift(4)).where(year)
    out["op_margin_chg"] = (out["op_margin"] - out["op_margin"].shift(4)).where(year)
    out["shares_yoy"] = (g["diluted_shares"] / g["diluted_shares"].shift(4) - 1).where(year)
    up = (out["rev_yoy_q"] > 0).astype(float).where(out["rev_yoy_q"].notna())
    out["rev_up_12q"] = up.rolling(12, min_periods=12).sum()
    out["rev_yoy_std_8q"] = out["rev_yoy_q"].rolling(8, min_periods=8).std()
    out["rev_yoy_mean_8q"] = out["rev_yoy_q"].rolling(8, min_periods=8).mean()
    out["debt_to_equity"] = g["debt"] / g["equity"].where(g["equity"] > 0)
    out["diluted_shares"] = g["diluted_shares"]
    out["quarters"] = np.arange(1, len(g) + 1)
    return out


def states(quarters: pd.DataFrame) -> pd.DataFrame:
    """One row per company per filed quarter, usable from `effective` (the day after filing)."""
    if quarters.empty:
        return pd.DataFrame()
    out = pd.concat([_company_states(g) for _, g in quarters.groupby("cik", sort=False)], ignore_index=True)
    out["effective"] = out["filed"] + pd.Timedelta(days=1)
    return out.sort_values(["effective", "cik"]).reset_index(drop=True)


class Fundamentals:
    """Company states by date, mapped to security ids, with market-cap multiples."""

    def __init__(self, con, panel):
        facts = con.execute('SELECT cik, metric, concept, priority, start, "end", value, form, filed, accn '
                            "FROM fundamental_facts").df()
        self.states = states(quarterly(facts))
        sec = con.execute("SELECT security_id, cik FROM securities WHERE cik IS NOT NULL").df()
        sec = sec[sec["cik"].astype(str).str.isdigit()]
        self.cik_of = dict(zip(sec["security_id"], sec["cik"].astype(int)))
        self.panel = panel
        self._known: dict[pd.Timestamp, pd.DataFrame] = {}

    def on(self, when: pd.Timestamp, ids: list[str]) -> pd.DataFrame:
        """Latest state effective on/before `when` for each security in `ids` (index security_id)."""
        if when not in self._known:                    # every category on a report date reads the same day
            if len(self._known) > 64:
                self._known.clear()
            self._known[when] = (self.states[self.states["effective"] <= when]
                                 .drop_duplicates("cik", keep="last").set_index("cik"))
        known = self._known[when]
        ciks = pd.Series({sid: self.cik_of.get(sid) for sid in ids}).dropna().astype(int)
        frame = known.reindex(ciks.to_numpy())
        frame.index = ciks.index
        frame = frame.dropna(subset=["end"])
        # A state older than ~6 months means the company stopped filing (acquired / foreign filer).
        return frame[(when - frame["end"]).dt.days <= 200]

    def market_cap(self, frame: pd.DataFrame, when: pd.Timestamp) -> pd.Series:
        """Diluted shares × unadjusted close at the quarter end × split-adjusted move since then
        (a quarter ending before our price history is anchored on the first close we have)."""
        panel = self.panel
        ids = [sid for sid in frame.index if sid in panel.close.columns]
        if not ids or when not in panel.close.index:
            return pd.Series(np.nan, index=frame.index)
        sub = frame.loc[ids]
        pos = np.clip(panel.sessions.searchsorted(sub["end"].to_numpy(), side="right") - 1, 0, None)
        cols = panel.close.columns.get_indexer(ids)
        raw = panel.raw_close.to_numpy()[pos, cols]
        adj_then = panel.close.to_numpy()[pos, cols]
        adj_now = panel.close.loc[when, ids].to_numpy()
        cap = sub["diluted_shares"].to_numpy() * raw * adj_now / adj_then
        return pd.Series(cap, index=ids, dtype=float).reindex(frame.index)

    def with_multiples(self, when: pd.Timestamp, ids: list[str], year_ago: pd.Timestamp | None = None) -> pd.DataFrame:
        """`on()` plus market_cap, P/S, P/E, FCF yield, and (with `year_ago`) the change in P/S and P/E."""
        frame = self.on(when, ids)
        if frame.empty:
            return frame
        cap = self.market_cap(frame, when)
        frame = frame.assign(market_cap=cap)
        frame["ps"] = cap / frame["revenue_ttm"].where(frame["revenue_ttm"] > 0)
        frame["pe"] = cap / frame["net_income_ttm"].where(frame["net_income_ttm"] > 0)
        frame["fcf_yield"] = frame["fcf_ttm"] / cap
        if year_ago is not None:
            past = self.on(year_ago, list(frame.index))
            past_cap = self.market_cap(past, year_ago)
            ps_then = (past_cap / past["revenue_ttm"].where(past["revenue_ttm"] > 0)).reindex(frame.index)
            pe_then = (past_cap / past["net_income_ttm"].where(past["net_income_ttm"] > 0)).reindex(frame.index)
            frame["ps_chg"] = frame["ps"] / ps_then - 1
            frame["pe_chg"] = frame["pe"] / pe_then - 1
        return frame
