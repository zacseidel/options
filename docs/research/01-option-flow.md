# Option flow → forward returns

_Generated 2026-10-21 by `python -m market.research.option_flow`._

Observations: 110,407 name-dates on 203 report dates, 2024-11-11 → 2026-10-19; in-sample before 2025-11-11.

Spread = top decile minus bottom decile, mean excess return vs SPY per date; t over dates (overlapping horizons inflate t at 21 / 63 sessions — read the out-of-sample column first).

## Summary (21 sessions)

| Feature | What | In-sample spread | t | Out-of-sample spread | t | Survives |
|---|---|---|---|---|---|---|
| `iv_rv` | 30-day implied vol ÷ 20-day realized vol | -0.84% | -2.2 | -1.46% | -4.2 | **yes** (low) |
| `term` | 30-day IV − long-dated IV (positive = inverted) | +0.77% | 1.9 | +1.15% | 1.7 | no |
| `otm_call_ratio` | Short-dated OTM call volume ÷ its prior 20-session mean | +0.37% | 1.5 | +0.50% | 1.6 | no |
| `call_vol_ratio` | Call volume ÷ its prior 20-session mean | +0.24% | 1.1 | +0.02% | 0.1 | no |
| `otm_call_share` | Short-dated OTM calls as a share of all call volume | -0.15% | -0.7 | +0.34% | 1.3 | no |
| `pc_ratio` | Put volume ÷ call volume | -0.13% | -0.7 | +0.12% | 0.4 | no |
| `call_premium_share` | Call premium ÷ (call + put premium) | +0.16% | 0.6 | -0.40% | -1.0 | no |
| `skew` | Put IV (88–95%) − call IV (105–112%), 20–60 DTE | -0.23% | -0.5 | -0.94% | -1.8 | no |
| `iv_change` | 30-day implied vol ÷ its prior 20-session mean | +0.16% | 0.5 | -0.38% | -0.8 | no |
| `pc_change` | Put/call ratio ÷ its prior 20-session mean | +0.04% | 0.2 | +0.29% | 1.0 | no |
| `skew_change` | Skew minus its prior 20-session mean | -0.05% | -0.1 | -0.07% | -0.1 | no |

## Robustness: realized vol ≥ 15% (drops deal-pinned names)

| Feature | What | In-sample spread | t | Out-of-sample spread | t | Survives |
|---|---|---|---|---|---|---|
| `term` | 30-day IV − long-dated IV (positive = inverted) | +0.83% | 2.1 | +1.21% | 1.8 | **yes** (high) |
| `iv_rv` | 30-day implied vol ÷ 20-day realized vol | -0.71% | -1.8 | -1.50% | -4.0 | no |
| `otm_call_ratio` | Short-dated OTM call volume ÷ its prior 20-session mean | +0.35% | 1.4 | +0.52% | 1.6 | no |
| `call_vol_ratio` | Call volume ÷ its prior 20-session mean | +0.23% | 1.1 | +0.06% | 0.2 | no |
| `pc_ratio` | Put volume ÷ call volume | -0.15% | -0.7 | +0.14% | 0.4 | no |
| `call_premium_share` | Call premium ÷ (call + put premium) | +0.19% | 0.7 | -0.34% | -0.8 | no |
| `otm_call_share` | Short-dated OTM calls as a share of all call volume | -0.14% | -0.6 | +0.30% | 1.1 | no |
| `skew` | Put IV (88–95%) − call IV (105–112%), 20–60 DTE | -0.26% | -0.6 | -0.99% | -1.9 | no |
| `iv_change` | 30-day implied vol ÷ its prior 20-session mean | +0.20% | 0.6 | -0.38% | -0.7 | no |
| `skew_change` | Skew minus its prior 20-session mean | -0.12% | -0.3 | -0.04% | -0.1 | no |
| `pc_change` | Put/call ratio ÷ its prior 20-session mean | +0.03% | 0.1 | +0.26% | 0.9 | no |

## By horizon

| Feature | 5d in | 5d out | 21d in | 21d out | 63d in | 63d out |
|---|---|---|---|---|---|---|
| `call_vol_ratio` | +0.24% | +0.18% | +0.24% | +0.02% | +0.52% | +1.10% |
| `otm_call_ratio` | +0.22% | +0.19% | +0.37% | +0.50% | +0.57% | +2.19% |
| `otm_call_share` | +0.05% | +0.11% | -0.15% | +0.34% | -0.94% | +1.97% |
| `call_premium_share` | +0.10% | +0.04% | +0.16% | -0.40% | +0.44% | -0.28% |
| `pc_ratio` | -0.06% | -0.09% | -0.13% | +0.12% | -0.39% | -0.65% |
| `pc_change` | -0.05% | -0.22% | +0.04% | +0.29% | +0.25% | +0.93% |
| `iv_rv` | -0.14% | -0.18% | -0.84% | -1.46% | -2.92% | -2.03% |
| `iv_change` | +0.16% | -0.20% | +0.16% | -0.38% | +0.09% | +0.85% |
| `skew` | +0.17% | +0.23% | -0.23% | -0.94% | -0.27% | -1.20% |
| `skew_change` | +0.07% | +0.30% | -0.05% | -0.07% | -0.40% | +0.05% |
| `term` | +0.32% | +0.05% | +0.77% | +1.15% | +4.25% | +3.17% |

## Deciles (21 sessions, mean excess return per date)

### `call_vol_ratio` — Call volume ÷ its prior 20-session mean

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.86% | -0.54% |
| 2 | -0.87% | -0.10% |
| 3 | -0.44% | -0.00% |
| 4 | -0.51% | +0.17% |
| 5 | -0.73% | +0.12% |
| 6 | -0.58% | +0.10% |
| 7 | -0.48% | +0.20% |
| 8 | -0.56% | -0.15% |
| 9 | -0.34% | +0.32% |
| 10 | -0.62% | -0.52% |

### `otm_call_ratio` — Short-dated OTM call volume ÷ its prior 20-session mean

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.99% | -0.67% |
| 2 | -0.82% | -0.17% |
| 3 | -0.69% | -0.04% |
| 4 | -0.50% | +0.04% |
| 5 | -0.41% | +0.07% |
| 6 | -0.48% | -0.06% |
| 7 | -0.37% | +0.07% |
| 8 | -0.67% | +0.39% |
| 9 | -0.43% | +0.20% |
| 10 | -0.63% | -0.17% |

### `otm_call_share` — Short-dated OTM calls as a share of all call volume

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.62% | -0.79% |
| 2 | -0.51% | -0.59% |
| 3 | -0.55% | +0.11% |
| 4 | -0.60% | -0.03% |
| 5 | -0.59% | -0.31% |
| 6 | -0.62% | +0.45% |
| 7 | -0.54% | +0.58% |
| 8 | -0.52% | +0.41% |
| 9 | -0.67% | +0.21% |
| 10 | -0.77% | -0.45% |

### `call_premium_share` — Call premium ÷ (call + put premium)

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.70% | -0.19% |
| 2 | -0.30% | -0.21% |
| 3 | -0.57% | -0.29% |
| 4 | -0.62% | +0.17% |
| 5 | -0.55% | +0.22% |
| 6 | -0.74% | +0.09% |
| 7 | -0.29% | +0.58% |
| 8 | -0.75% | -0.04% |
| 9 | -0.92% | -0.16% |
| 10 | -0.54% | -0.59% |

### `pc_ratio` — Put volume ÷ call volume

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.69% | -0.49% |
| 2 | -0.62% | +0.08% |
| 3 | -0.60% | +0.02% |
| 4 | -0.75% | +0.10% |
| 5 | -0.51% | +0.10% |
| 6 | -0.25% | +0.08% |
| 7 | -0.53% | +0.36% |
| 8 | -0.52% | -0.10% |
| 9 | -0.69% | -0.19% |
| 10 | -0.82% | -0.37% |

### `pc_change` — Put/call ratio ÷ its prior 20-session mean

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.84% | -0.51% |
| 2 | -1.01% | -0.36% |
| 3 | -0.60% | -0.24% |
| 4 | -0.88% | -0.08% |
| 5 | -0.70% | +0.34% |
| 6 | -0.31% | -0.18% |
| 7 | -0.09% | +0.35% |
| 8 | -0.25% | +0.27% |
| 9 | -0.51% | +0.24% |
| 10 | -0.80% | -0.23% |

### `iv_rv` — 30-day implied vol ÷ 20-day realized vol

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.24% | +0.42% |
| 2 | +0.20% | -0.23% |
| 3 | -0.02% | +0.45% |
| 4 | -0.27% | +0.03% |
| 5 | -0.79% | +0.28% |
| 6 | -0.69% | +0.32% |
| 7 | -0.84% | +0.17% |
| 8 | -0.97% | +0.19% |
| 9 | -0.92% | -0.38% |
| 10 | -1.08% | -1.03% |

### `iv_change` — 30-day implied vol ÷ its prior 20-session mean

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.87% | -0.27% |
| 2 | -0.36% | -0.32% |
| 3 | -0.17% | -0.00% |
| 4 | -0.33% | +0.04% |
| 5 | -0.23% | +0.13% |
| 6 | -0.48% | +0.37% |
| 7 | -0.33% | +0.61% |
| 8 | -0.79% | +0.38% |
| 9 | -0.73% | +0.27% |
| 10 | -0.71% | -0.65% |

### `skew` — Put IV (88–95%) − call IV (105–112%), 20–60 DTE

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.36% | +0.82% |
| 2 | -0.37% | +0.07% |
| 3 | -0.52% | -0.07% |
| 4 | -0.60% | +0.20% |
| 5 | -0.74% | -0.13% |
| 6 | -0.71% | +0.06% |
| 7 | -0.51% | +0.14% |
| 8 | -0.58% | -0.22% |
| 9 | -0.57% | -0.18% |
| 10 | -0.59% | -0.11% |

### `skew_change` — Skew minus its prior 20-session mean

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -0.55% | +0.49% |
| 2 | -0.84% | +0.42% |
| 3 | -0.47% | -0.22% |
| 4 | -0.40% | +0.10% |
| 5 | -0.42% | +0.15% |
| 6 | -0.35% | -0.06% |
| 7 | -0.66% | -0.00% |
| 8 | -0.69% | -0.04% |
| 9 | -0.56% | +0.04% |
| 10 | -0.61% | +0.42% |

### `term` — 30-day IV − long-dated IV (positive = inverted)

| decile | in-sample | out-of-sample |
|---|---|---|
| 1 | -1.17% | -0.71% |
| 2 | -0.98% | -0.39% |
| 3 | -0.46% | -0.17% |
| 4 | -0.47% | +0.20% |
| 5 | -0.19% | +0.13% |
| 6 | -0.18% | +0.04% |
| 7 | -0.46% | +0.28% |
| 8 | -0.61% | +0.17% |
| 9 | -0.71% | +0.54% |
| 10 | -0.40% | +0.45% |

