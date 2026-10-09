"""Black-Scholes pricing, delta and implied volatility (vectorized; PLAN §7b).

Listed equity options are American; Black-Scholes with a continuous dividend yield is used
only to rank contracts by delta and to mark a held contract on a day it didn't trade, which
is accurate enough for both. Times are in years (calendar days / 365).
"""

from __future__ import annotations

import math

import numpy as np

def ndtr(x):
    """Standard normal CDF (Abramowitz & Stegun 7.1.26 erf, |error| < 1.5e-7)."""
    z = np.asarray(x, dtype=float) / math.sqrt(2.0)
    a = np.abs(z)
    k = 1.0 / (1.0 + 0.3275911 * a)
    poly = k * (0.254829592 + k * (-0.284496736 + k * (1.421413741 + k * (-1.453152027 + k * 1.061405429))))
    erf = 1.0 - poly * np.exp(-a * a)
    return 0.5 * (1.0 + np.sign(z) * erf)


MIN_T = 1.0 / 365.0
IV_BOUNDS = (0.01, 5.0)


def _d1_d2(spot, strike, t, rate, div, vol):
    t = np.maximum(t, MIN_T)
    sq = vol * np.sqrt(t)
    d1 = (np.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / sq
    return d1, d1 - sq, t


def price(kind, spot, strike, t, rate, div, vol):
    """Option value per share. kind: 'C'/'P' (scalar or array)."""
    spot, strike, t, vol = (np.asarray(x, dtype=float) for x in (spot, strike, t, vol))
    d1, d2, tt = _d1_d2(spot, strike, t, rate, div, vol)
    df_s, df_k = np.exp(-div * tt), np.exp(-rate * tt)
    call = spot * df_s * ndtr(d1) - strike * df_k * ndtr(d2)
    put = strike * df_k * ndtr(-d2) - spot * df_s * ndtr(-d1)
    out = np.where(np.asarray(kind) == "C", call, put)
    # At/after expiry the option is worth its intrinsic value.
    intrinsic = np.where(np.asarray(kind) == "C", np.maximum(spot - strike, 0), np.maximum(strike - spot, 0))
    return np.where(t <= 0, intrinsic, np.maximum(out, 0.0))


def delta(kind, spot, strike, t, rate, div, vol):
    spot, strike, t, vol = (np.asarray(x, dtype=float) for x in (spot, strike, t, vol))
    d1, _, tt = _d1_d2(spot, strike, t, rate, div, vol)
    df_s = np.exp(-div * tt)
    return np.where(np.asarray(kind) == "C", df_s * ndtr(d1), df_s * (ndtr(d1) - 1.0))


def implied_vol(kind, premium, spot, strike, t, rate, div, iterations: int = 40):
    """Bisection on volatility; NaN where the premium is outside the no-arbitrage range."""
    kind = np.asarray(kind)
    premium, spot, strike, t = (np.asarray(x, dtype=float) for x in (premium, spot, strike, t))
    lo = np.full(premium.shape, IV_BOUNDS[0])
    hi = np.full(premium.shape, IV_BOUNDS[1])
    p_lo = price(kind, spot, strike, t, rate, div, lo)
    p_hi = price(kind, spot, strike, t, rate, div, hi)
    valid = (premium > p_lo) & (premium < p_hi) & np.isfinite(premium)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        above = price(kind, spot, strike, t, rate, div, mid) > premium
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
    return np.where(valid, 0.5 * (lo + hi), np.nan)
