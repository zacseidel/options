"""Option flow: a one-row-per-underlying daily summary of the whole OPRA file (PLAN-signals §3).

The option panel keeps contract rows only for the select option set; this keeps a small summary for
every security we price, computed from the same streamed file, so it costs no extra downloads. The
summary is what the option-flow research and categories read: call / put volume and premium,
short-dated out-of-the-money volume, ATM implied volatility (~30 d and long-dated) and put–call skew.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from market.data.options import parse_occ
from market.methods.option_math import implied_vol

FLOW_COLUMNS = ["session", "security_id", "root", "call_volume", "put_volume", "call_premium", "put_premium",
                "otm_call_volume", "otm_put_volume", "contracts", "iv30", "iv_long", "skew"]

OTM_DTE = (0, 30)
OTM_CALL = (1.00, 1.15)
OTM_PUT = (0.85, 1.00)
IV30_DTE, IV30_MONEY = (20, 45), (0.95, 1.05)
IVLONG_DTE, IVLONG_MONEY = (120, 400), (0.90, 1.10)
SKEW_DTE, SKEW_PUT, SKEW_CALL = (20, 60), (0.88, 0.95), (1.05, 1.12)


def _weighted(frame: pd.DataFrame, mask: pd.Series) -> pd.Series:
    """Volume-weighted mean IV per root over the rows in `mask` (rows without an IV are skipped)."""
    part = frame.loc[mask & frame["iv"].notna(), ["root", "iv", "volume"]]
    if part.empty:
        return pd.Series(dtype=float)
    weight = part["volume"].clip(lower=1)
    return (part["iv"] * weight).groupby(part["root"]).sum() / weight.groupby(part["root"]).sum()


def summarize(rows: pd.DataFrame, session: date, spot_by_root: dict[str, tuple[str, float]], rate: float) -> pd.DataFrame:
    """rows: one OPRA day-aggregates file; spot_by_root: OCC root → (security_id, unadjusted close)."""
    terms = parse_occ(rows["ticker"])
    keep = terms["root"].isin(spot_by_root.keys()) & (rows["volume"] > 0)
    terms, rows = terms[keep], rows[keep]
    if terms.empty:
        return pd.DataFrame(columns=FLOW_COLUMNS)
    spot = terms["root"].map({r: v[1] for r, v in spot_by_root.items()}).astype(float)
    frame = pd.DataFrame({
        "root": terms["root"], "kind": terms["type"], "strike": terms["strike"],
        "dte": (terms["expiry"] - pd.Timestamp(session)).dt.days,
        "close": rows["close"].astype(float), "volume": rows["volume"].astype(float), "spot": spot,
    })
    frame["money"] = frame["strike"] / frame["spot"]
    frame["premium"] = frame["volume"] * frame["close"] * 100
    call, put = frame["kind"].eq("C"), frame["kind"].eq("P")
    short = frame["dte"].between(*OTM_DTE)

    # IVs only where they feed a summary (keeps the bisection to a small slice of the file).
    iv30 = frame["dte"].between(*IV30_DTE) & frame["money"].between(*IV30_MONEY) & (
        (call & (frame["money"] >= 1)) | (put & (frame["money"] < 1)))
    ivlong = frame["dte"].between(*IVLONG_DTE) & frame["money"].between(*IVLONG_MONEY) & (
        (call & (frame["money"] >= 1)) | (put & (frame["money"] < 1)))
    skew_put = put & frame["dte"].between(*SKEW_DTE) & frame["money"].between(*SKEW_PUT)
    skew_call = call & frame["dte"].between(*SKEW_DTE) & frame["money"].between(*SKEW_CALL)
    need = iv30 | ivlong | skew_put | skew_call
    frame["iv"] = np.nan
    sub = frame[need]
    frame.loc[need, "iv"] = implied_vol(sub["kind"].to_numpy(), sub["close"].to_numpy(), sub["spot"].to_numpy(),
                                        sub["strike"].to_numpy(), sub["dte"].to_numpy() / 365.0, rate, 0.0)

    g = frame.groupby("root")
    out = pd.DataFrame({
        "call_volume": frame["volume"].where(call, 0).groupby(frame["root"]).sum(),
        "put_volume": frame["volume"].where(put, 0).groupby(frame["root"]).sum(),
        "call_premium": frame["premium"].where(call, 0).groupby(frame["root"]).sum(),
        "put_premium": frame["premium"].where(put, 0).groupby(frame["root"]).sum(),
        "otm_call_volume": frame["volume"].where(call & short & frame["money"].between(*OTM_CALL), 0).groupby(frame["root"]).sum(),
        "otm_put_volume": frame["volume"].where(put & short & frame["money"].between(*OTM_PUT), 0).groupby(frame["root"]).sum(),
        "contracts": g.size(),
    })
    out["iv30"] = _weighted(frame, iv30)
    out["iv_long"] = _weighted(frame, ivlong)
    out["skew"] = _weighted(frame, skew_put) - _weighted(frame, skew_call)
    out = out.reset_index(names="root")
    out["session"] = pd.Timestamp(session)
    out["security_id"] = out["root"].map({r: v[0] for r, v in spot_by_root.items()})
    for col in ("call_volume", "put_volume", "otm_call_volume", "otm_put_volume", "contracts"):
        out[col] = out[col].astype(np.int64)
    return out[FLOW_COLUMNS]


# ------------------------------------------------------------------ features (research + categories)
LOOKBACK = 20
MIN_OPTION_VOLUME = 500           # contracts a day (calls + puts), prior-20-session mean, to count as liquid

FEATURES = {
    "call_vol_ratio": "Call volume ÷ its prior 20-session mean",
    "otm_call_ratio": "Short-dated OTM call volume ÷ its prior 20-session mean",
    "otm_call_share": "Short-dated OTM calls as a share of all call volume",
    "call_premium_share": "Call premium ÷ (call + put premium)",
    "pc_ratio": "Put volume ÷ call volume",
    "pc_change": "Put/call ratio ÷ its prior 20-session mean",
    "iv_rv": "30-day implied vol ÷ 20-day realized vol",
    "iv_change": "30-day implied vol ÷ its prior 20-session mean",
    "skew": "Put IV (88–95%) − call IV (105–112%), 20–60 DTE",
    "skew_change": "Skew minus its prior 20-session mean",
    "term": "30-day IV − long-dated IV (positive = inverted)",
}


def _wide(flow: pd.DataFrame, column: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    return flow.pivot(index="session", columns="security_id", values=column).reindex(sessions)


def feature_panel(con, panel) -> pd.DataFrame:
    """Long frame (date, security_id, liquid, rv20, <FEATURES>): each value uses only that session and earlier."""
    flow = con.execute("SELECT * FROM option_flow_daily").df()
    flow["session"] = pd.to_datetime(flow["session"])
    sessions = panel.sessions[panel.sessions >= flow["session"].min()]
    w = {c: _wide(flow, c, sessions) for c in ("call_volume", "put_volume", "otm_call_volume", "call_premium",
                                               "put_premium", "iv30", "iv_long", "skew")}
    calls = w["call_volume"].fillna(0)
    puts = w["put_volume"].fillna(0)
    prior = lambda frame: frame.shift(1).rolling(LOOKBACK, min_periods=15).mean()      # noqa: E731
    pc = puts / calls.replace(0, np.nan)
    close = panel.close.reindex(index=sessions, columns=calls.columns)
    rv = np.log(close).diff().rolling(LOOKBACK, min_periods=15).std() * np.sqrt(252)
    feats = {
        "call_vol_ratio": calls / prior(calls),
        "otm_call_ratio": w["otm_call_volume"].fillna(0) / prior(w["otm_call_volume"].fillna(0)),
        "otm_call_share": w["otm_call_volume"] / calls.replace(0, np.nan),
        "call_premium_share": w["call_premium"] / (w["call_premium"] + w["put_premium"]).replace(0, np.nan),
        "pc_ratio": pc,
        "pc_change": pc / prior(pc),
        "iv_rv": w["iv30"] / rv,
        "iv_change": w["iv30"] / prior(w["iv30"]),
        "skew": w["skew"],
        "skew_change": w["skew"] - prior(w["skew"]),
        "term": w["iv30"] - w["iv_long"],
        "rv20": rv,
        "liquid": prior(calls + puts) >= MIN_OPTION_VOLUME,
    }
    stacked = pd.concat({k: v.stack(future_stack=True) for k, v in feats.items()}, axis=1)
    stacked.index.names = ["date", "security_id"]
    return stacked.reset_index()
