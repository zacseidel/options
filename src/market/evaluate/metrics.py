"""Standard evaluation metrics — the same set for every strategy and benchmark.

Ported from the eval repo (Sharpe on daily log returns, half-Kelly with a closed-trade
minimum) and extended with CAGR, drawdown, Sortino, beta/alpha and exposure.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _clean(value):
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    return round(float(value), 6)


def performance(nav: pd.Series, risk_free: float, benchmark: pd.Series | None = None) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    log_ret = np.log(nav / nav.shift(1)).dropna()
    rf_daily = math.log1p(risk_free) / TRADING_DAYS
    excess = log_ret - rf_daily
    downside = excess[excess < 0]
    running_max = nav.cummax()
    drawdown = nav / running_max - 1
    trough = drawdown.idxmin()
    peak = nav.loc[:trough].idxmax()
    total = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else None
    out = {
        "start": str(nav.index[0].date()), "end": str(nav.index[-1].date()), "years": round(years, 2),
        "total_return": total,
        "cagr": cagr,
        "volatility": log_ret.std() * math.sqrt(TRADING_DAYS),
        "sharpe": excess.mean() / log_ret.std() * math.sqrt(TRADING_DAYS) if log_ret.std() > 0 else None,
        "sortino": excess.mean() / downside.std() * math.sqrt(TRADING_DAYS) if len(downside) > 1 else None,
        "max_drawdown": drawdown.min(),
        "max_drawdown_peak": str(peak.date()), "max_drawdown_trough": str(trough.date()),
        "calmar": cagr / abs(drawdown.min()) if cagr is not None and drawdown.min() < 0 else None,
    }
    if benchmark is not None:
        bench = benchmark.reindex(nav.index).ffill().dropna()
        if len(bench) > 2:
            b_ret = np.log(bench / bench.shift(1)).dropna()
            joined = pd.concat([log_ret, b_ret], axis=1, join="inner").dropna()
            if len(joined) > 20 and joined.iloc[:, 1].var() > 0:
                beta = joined.cov().iloc[0, 1] / joined.iloc[:, 1].var()
                alpha = (joined.iloc[:, 0].mean() - rf_daily - beta * (joined.iloc[:, 1].mean() - rf_daily)) * TRADING_DAYS
                out.update({"beta": beta, "alpha": alpha, "correlation": joined.corr().iloc[0, 1]})
            b_total = bench.iloc[-1] / bench.iloc[0] - 1
            out["benchmark_total_return"] = b_total
            out["excess_total_return"] = total - b_total
            if years > 0:
                b_cagr = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
                out["benchmark_cagr"] = b_cagr
                out["excess_cagr"] = (cagr - b_cagr) if cagr is not None else None
    return {k: (_clean(v) if not isinstance(v, str) else v) for k, v in out.items()}


def trade_stats(returns: pd.Series, hold_days: pd.Series, min_closed: int) -> dict:
    """Closed-trade outcomes and eval's half-Kelly: 0.5 · max(0, p − q / b)."""
    returns = returns.dropna()
    wins, losses = returns[returns > 0], returns[returns < 0]
    decided = len(wins) + len(losses)
    payoff = wins.mean() / abs(losses.mean()) if len(wins) and len(losses) else None
    kelly = None
    if len(returns) >= min_closed and decided and payoff:
        p, q = len(wins) / decided, len(losses) / decided
        kelly = 0.5 * max(0.0, p - q / payoff)
    out = {
        "closed_trades": int(len(returns)),
        "win_rate": len(wins) / len(returns) if len(returns) else None,
        "avg_win": wins.mean() if len(wins) else None,
        "avg_loss": losses.mean() if len(losses) else None,
        "avg_trade": returns.mean() if len(returns) else None,
        "payoff_ratio": payoff,
        "half_kelly": kelly,
        "avg_hold_days": hold_days.mean() if len(hold_days) else None,
        "median_hold_days": hold_days.median() if len(hold_days) else None,
    }
    return {k: (_clean(v) if not isinstance(v, (int, str)) or isinstance(v, bool) else v) for k, v in out.items()}
