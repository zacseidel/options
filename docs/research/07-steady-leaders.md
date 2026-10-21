# Steady leaders: consistency within the top 50

_Generated 2026-10-21 by `python -m market.research.steady_leaders`._

> **Outcome (2026-10-21).** Only longevity (S&P 500) showed an edge; smoothness did not, and nothing
> worked in the S&P 400. Built as the Lab category S&P 500 Steady Leaders: from 2023-04, top 5 by
> longevity returned 49% a year (Sharpe 0.96) vs 30% (0.62) for S&P 500 Leaders ranks 6–10 and 69%
> (1.05) for the Leaders' top 5; its ranks 6–10 were weak (10%) and were not kept.

49 monthly dates, 2022-10-21 → 2026-10-02; in-sample before 2025-01-01. Returns vs the average member of the same index.

## SP500 — pool = ranks 6–50 by 12-month return

| Group | n in | 63d in | 126d in | n out | 63d out | 126d out |
|---|---|---|---|---|---|---|
| top 5 (the Leaders) | 135 | +4.60% | +11.30% | 110 | +14.19% | +29.41% |
| whole pool (6–50) | 1215 | +0.48% | +3.43% | 990 | +3.07% | +7.67% |

| Measure (top − bottom quintile of the pool) | 63d in | t | 63d out | t | 126d in | 126d out | top quintile 63d in / out |
|---|---|---|---|---|---|---|---|
| `longevity` Share of the last 26 weeks in the top 50 | +5.06% | 2.4 | +4.81% | 1.2 | +10.51% | -4.01% | +5.45% / +6.85% |
| `smooth_126` Up days − down days, last 126 sessions | -1.75% | -1.0 | -1.03% | -0.3 | +0.13% | -2.03% | +0.66% / +4.01% |
| `smooth_252` Up days − down days, last 252 sessions | -0.35% | -0.2 | -8.93% | -2.5 | +2.60% | -14.34% | +1.39% / -1.24% |
| `trend_r2` R² of a straight-line fit to log price, last 126 sessions | -2.30% | -1.4 | +1.86% | 0.5 | -0.09% | +5.52% | -0.21% / +4.15% |
| `up_weeks` Share of up weeks, last 26 | -0.70% | -0.4 | +2.60% | 1.1 | -0.04% | +5.97% | +1.51% / +3.79% |
| `jumpiness` Best 21-session gain ÷ 12-month gain (lower = steadier) | +1.38% | 0.8 | +8.25% | 1.8 | -1.01% | +15.19% | +0.50% / +7.94% |
| `jumpiness_inv` −jumpiness (higher = steadier) | -1.38% | -0.8 | -8.25% | -1.8 | +1.01% | -15.19% | -0.88% / -0.31% |
| `composite` Mean percentile of longevity, smooth_126 and trend_r2 | -0.34% | -0.2 | +3.22% | 0.9 | +4.20% | -0.69% | +0.15% / +4.98% |

## SP400 — pool = ranks 6–50 by 12-month return

| Group | n in | 63d in | 126d in | n out | 63d out | 126d out |
|---|---|---|---|---|---|---|
| top 5 (the Leaders) | 135 | +7.49% | +16.76% | 110 | +9.67% | +18.23% |
| whole pool (6–50) | 1215 | +0.53% | +1.97% | 990 | +1.32% | +5.48% |

| Measure (top − bottom quintile of the pool) | 63d in | t | 63d out | t | 126d in | 126d out | top quintile 63d in / out |
|---|---|---|---|---|---|---|---|
| `longevity` Share of the last 26 weeks in the top 50 | +0.75% | 0.3 | -1.94% | -0.7 | -2.74% | +0.35% | +0.76% / -2.00% |
| `smooth_126` Up days − down days, last 126 sessions | +1.23% | 0.7 | -1.40% | -0.6 | +1.94% | -3.90% | +1.80% / -0.45% |
| `smooth_252` Up days − down days, last 252 sessions | +2.88% | 1.8 | -1.02% | -0.6 | +1.73% | +1.48% | +2.14% / +0.68% |
| `trend_r2` R² of a straight-line fit to log price, last 126 sessions | -1.91% | -1.0 | -1.26% | -0.5 | +4.41% | -0.82% | +0.40% / +0.47% |
| `up_weeks` Share of up weeks, last 26 | -0.53% | -0.4 | +0.81% | 0.3 | +2.65% | +8.90% | +0.86% / +0.36% |
| `jumpiness` Best 21-session gain ÷ 12-month gain (lower = steadier) | -1.17% | -0.6 | +3.79% | 1.5 | -4.24% | +2.28% | +0.17% / +1.95% |
| `jumpiness_inv` −jumpiness (higher = steadier) | +1.17% | 0.6 | -3.79% | -1.5 | +4.24% | -2.28% | +1.35% / -1.84% |
| `composite` Mean percentile of longevity, smooth_126 and trend_r2 | -0.13% | -0.1 | -2.31% | -0.8 | +1.50% | -3.57% | +1.57% / +2.59% |

