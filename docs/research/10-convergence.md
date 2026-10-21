# Convergence across signal families

_Generated 2026-10-21 by `python -m market.research.convergence`._

> **Outcome (2026-10-21).** Returns rise with the number of families flagging a name, in both halves;
> momentum + fundamentals is the strongest consistent pair. As top-5 strategies (from 2022-11) Convergence
> returned 39% a year (Sharpe 0.74) and Momentum + Fundamentals 38% (0.68): about twice SPY but at a lower
> Sharpe, and below the momentum lists they overlap with (S&P 500 Leaders 60%, 0.96). Kept in the Lab for
> the user's call.

203 Friday reports, 2022-12-01 → 2026-10-15; name-dates flagged by at least one family: 35,524. Mean excess return vs the average member.

## By number of families

| Group | n in | 21d | 63d | 126d | hit 63d | n out | 21d | 63d | 126d | hit 63d |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 family | 15773 | +0.46% | +1.34% | +2.84% | 51.45% | 13751 | +0.22% | +0.89% | +2.08% | 46.32% |
| 2 families | 2631 | +1.00% | +1.78% | +4.68% | 51.11% | 2463 | +2.29% | +6.34% | +16.55% | 52.57% |
| 3+ families | 255 | +0.65% | +5.15% | +13.48% | 60.78% | 651 | +4.41% | +11.47% | +25.57% | 50.39% |

## Each family alone vs with at least one other family

| Group | n in | 21d | 63d | 126d | hit 63d | n out | 21d | 63d | 126d | hit 63d |
|---|---|---|---|---|---|---|---|---|---|---|
| momentum only | 3469 | +0.82% | +2.52% | +6.72% | 51.87% | 2508 | +0.90% | +2.09% | +5.00% | 48.51% |
| momentum + another | 2255 | +0.91% | +1.97% | +6.05% | 51.15% | 2370 | +3.39% | +8.81% | +22.24% | 52.55% |
| fundamentals only | 4063 | +0.38% | +1.53% | +2.57% | 51.60% | 3142 | +0.84% | +3.13% | +6.33% | 51.24% |
| fundamentals + another | 1719 | +1.26% | +3.56% | +7.65% | 53.47% | 1723 | +3.19% | +8.04% | +20.89% | 52.07% |
| reversion only | 778 | +1.13% | +3.47% | +5.35% | 56.56% | 585 | +0.82% | +0.93% | -0.79% | 50.00% |
| reversion + another | 226 | +0.49% | +2.07% | +4.01% | 57.52% | 308 | +1.64% | +3.50% | +4.75% | 53.95% |
| events only | 7404 | +0.23% | +0.42% | +0.87% | 50.56% | 6086 | -0.46% | -0.82% | -1.10% | 43.50% |
| events + another | 1816 | +0.77% | +1.37% | +4.11% | 52.24% | 1320 | +2.35% | +6.43% | +16.27% | 51.26% |
| options only | 59 | +3.82% | +5.72% | +8.32% | 60.34% | 742 | -0.12% | +1.07% | +1.14% | 42.83% |
| options + another | 11 | +2.46% | -15.87% | -13.09% | 27.27% | 197 | +3.03% | +11.48% | +21.31% | 57.50% |
| smart_money only | 0 | — | — | — | — | 688 | +1.13% | +1.57% | +4.23% | 42.32% |
| smart_money + another | 0 | — | — | — | — | 1039 | +3.03% | +8.11% | +15.94% | 50.64% |

## Pairs (both families flag the name)

| Group | n in | 21d | 63d | 126d | hit 63d | n out | 21d | 63d | 126d | hit 63d |
|---|---|---|---|---|---|---|---|---|---|---|
| momentum + fundamentals | 1156 | +1.24% | +4.16% | +9.90% | 53.29% | 1241 | +4.11% | +9.67% | +26.13% | 51.95% |
| momentum + reversion | 128 | +0.62% | +1.07% | +2.27% | 56.25% | 120 | +1.29% | +1.88% | +4.95% | 53.85% |
| momentum + events | 1215 | +0.56% | +0.77% | +4.48% | 50.82% | 837 | +3.32% | +8.95% | +22.94% | 53.28% |
| momentum + options | 7 | +1.75% | -18.05% | -14.79% | 14.29% | 139 | +4.43% | +15.90% | +25.44% | 58.56% |
| momentum + smart_money | 0 | — | — | — | — | 741 | +4.41% | +11.12% | +22.28% | 50.83% |
| fundamentals + reversion | 33 | +1.88% | +4.63% | +10.38% | 54.55% | 37 | +5.46% | +13.77% | +18.91% | 68.57% |
| fundamentals + events | 776 | +1.06% | +3.23% | +6.25% | 55.84% | 583 | +3.54% | +10.11% | +19.27% | 54.35% |
| fundamentals + options | 4 | +3.72% | -12.05% | -10.11% | 50.00% | 72 | +7.31% | +12.23% | +28.69% | 59.38% |
| fundamentals + smart_money | 0 | — | — | — | — | 407 | +2.95% | +5.69% | +10.26% | 45.30% |
| reversion + events | 77 | +0.22% | +3.54% | +5.84% | 64.94% | 45 | +0.90% | +0.72% | -2.99% | 45.00% |
| reversion + smart_money | 0 | — | — | — | — | 191 | +2.11% | +3.77% | +5.51% | 53.07% |
| events + smart_money | 0 | — | — | — | — | 196 | +4.75% | +10.66% | +16.31% | 50.00% |
| options + smart_money | 0 | — | — | — | — | 22 | +2.26% | +20.29% | +122.36% | 70.59% |
