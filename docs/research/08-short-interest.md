# Short interest → forward returns

_Generated 2026-10-21 by `python -m market.research.short_interest`._

> **Outcome (2026-10-21).** Days to cover is the signal. Kept: S&P 500 Leaders skipping the top fifth
> of days to cover (68% a year, Sharpe 1.07 vs 60% / 0.96 unfiltered, from 2022-11). The same filter
> made S&P 400 Leaders and S&P 500 Rank Momentum worse, so those were dropped.

52,307 name-months, 58 monthly dates 2022-01-03 → 2026-10-01; readings used from settlement + 8 business days; in-sample before 2025-01-01. Returns vs the average member of the same index.

## SP500 — all members

| Measure (top − bottom quintile) | 63d in | t | 63d out | t | 126d in | 126d out | Q1 / Q5 63d in | Q1 / Q5 63d out |
|---|---|---|---|---|---|---|---|---|
| `short_pct` Short interest ÷ diluted shares | -1.81% | -2.4 | +1.11% | 1.3 | -4.40% | +4.55% | +0.92% / -0.89% | -0.26% / +0.85% |
| `dtc` Days to cover | -1.87% | -4.7 | -2.67% | -2.1 | -3.72% | -6.96% | +1.02% / -0.85% | +1.94% / -0.73% |
| `si_change` Change in short interest vs ~1 month earlier | -0.10% | -0.3 | -0.69% | -1.2 | -0.45% | -1.55% | -0.14% / -0.24% | +0.22% / -0.47% |
| `dtc_change` Change in days to cover vs ~1 month earlier | -0.11% | -0.3 | -0.86% | -1.3 | +0.05% | -0.41% | -0.38% / -0.49% | +0.09% / -0.77% |

## SP500 — top 50 by 12-month return

| Measure (top − bottom quintile) | 63d in | t | 63d out | t | 126d in | 126d out | Q1 / Q5 63d in | Q1 / Q5 63d out |
|---|---|---|---|---|---|---|---|---|
| `short_pct` Short interest ÷ diluted shares | -3.53% | -2.2 | +3.75% | 1.2 | -7.16% | +11.47% | +2.38% / -1.15% | +0.78% / +4.54% |
| `dtc` Days to cover | -2.41% | -1.4 | -9.48% | -1.7 | -3.74% | -17.30% | +4.19% / +1.79% | +9.53% / +0.05% |
| `si_change` Change in short interest vs ~1 month earlier | +1.24% | 1.0 | -0.79% | -0.4 | +1.12% | -5.62% | +0.51% / +1.74% | +2.94% / +2.15% |
| `dtc_change` Change in days to cover vs ~1 month earlier | +1.00% | 0.7 | -0.89% | -0.3 | +1.22% | -5.35% | +0.63% / +1.63% | +2.94% / +2.05% |

## SP400 — all members

| Measure (top − bottom quintile) | 63d in | t | 63d out | t | 126d in | 126d out | Q1 / Q5 63d in | Q1 / Q5 63d out |
|---|---|---|---|---|---|---|---|---|
| `short_pct` Short interest ÷ diluted shares | -1.59% | -2.3 | +0.38% | 0.5 | -4.65% | +0.58% | +0.89% / -0.70% | -0.44% / -0.06% |
| `dtc` Days to cover | -2.13% | -3.7 | -2.98% | -2.5 | -4.85% | -7.75% | +1.02% / -1.10% | +1.51% / -1.47% |
| `si_change` Change in short interest vs ~1 month earlier | +0.37% | 0.7 | +0.70% | 0.9 | +0.20% | -1.49% | +0.01% / +0.37% | +0.15% / +0.86% |
| `dtc_change` Change in days to cover vs ~1 month earlier | +0.32% | 0.6 | +1.14% | 1.4 | +0.12% | +0.94% | -0.80% / -0.48% | -1.26% / -0.12% |

## SP400 — top 50 by 12-month return

| Measure (top − bottom quintile) | 63d in | t | 63d out | t | 126d in | 126d out | Q1 / Q5 63d in | Q1 / Q5 63d out |
|---|---|---|---|---|---|---|---|---|
| `short_pct` Short interest ÷ diluted shares | +2.77% | 1.4 | -1.06% | -0.6 | +6.24% | -0.33% | +0.62% / +3.39% | +3.18% / +2.11% |
| `dtc` Days to cover | -4.11% | -2.0 | -3.60% | -1.5 | -9.24% | -14.26% | +4.59% / +0.48% | +1.24% / -2.36% |
| `si_change` Change in short interest vs ~1 month earlier | +4.28% | 2.1 | +1.25% | 0.6 | +6.28% | +2.30% | -0.98% / +3.30% | +1.24% / +2.48% |
| `dtc_change` Change in days to cover vs ~1 month earlier | +0.39% | 0.3 | -0.96% | -0.3 | +2.21% | -6.05% | -0.33% / +0.06% | +1.12% / +0.17% |

