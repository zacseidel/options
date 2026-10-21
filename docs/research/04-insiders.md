# Insider buying → forward returns

> **Dropped 2026-10-21** (no benefit). The code that produced this report was removed; this is the record.

_Generated 2026-10-21 by `python -m market.research.insiders`._

3,512 insider purchase days at S&P 500 / 400 members, 2021-10-18 → 2026-04-08 (739 companies); in-sample before 2025-01-01. Fundamental Momentum known for 70% of events.

Returns are excess vs the average S&P 500 / 400 stock over the same window (vs SPY minus the universe's own excess), so 0% means 'no better than a random member'.

## Rules (mean excess vs the universe per event)

| Rule | Events in | 21d | 63d | 126d | hit 63d | Events out | 21d | 63d | 126d | hit 63d |
|---|---|---|---|---|---|---|---|---|---|---|
| every insider purchase day | 2531 | +0.26% | +0.83% | +0.77% | 52% | 981 | -0.38% | -1.32% | -2.19% | 44% |
| first buy in 30 days | 1687 | +0.24% | +0.65% | +0.88% | 53% | 664 | -0.42% | -0.86% | -1.53% | 44% |
| first buy, ≥ $100k | 1194 | +0.35% | +0.79% | +0.49% | 52% | 497 | -0.32% | -0.41% | -1.16% | 47% |
| C-suite buy ≥ $250k | 378 | +0.82% | +1.05% | +0.06% | 49% | 174 | -0.45% | -0.93% | -2.64% | 43% |
| cluster forms (≥ 2 insiders in 30 days) | 445 | +0.05% | +0.39% | -0.45% | 51% | 203 | -0.70% | -3.27% | -3.74% | 39% |
| cluster of ≥ 3 insiders | 445 | +0.05% | +0.39% | -0.45% | 51% | 203 | -0.70% | -3.27% | -3.74% | 39% |
| cluster, quality (fmom ≥ 0.5) | 150 | +0.19% | -0.23% | -1.77% | 55% | 57 | -1.17% | -4.45% | -3.24% | 39% |
| cluster, turnaround (fmom < 0.5) | 149 | +0.59% | -0.07% | -1.10% | 47% | 92 | -0.51% | -2.27% | -3.62% | 46% |
| first buy ≥ $100k, quality | 436 | +0.38% | +0.26% | +0.43% | 50% | 170 | -1.09% | -1.36% | -1.90% | 41% |
| first buy ≥ $100k, turnaround | 433 | +0.80% | +0.68% | -0.66% | 53% | 227 | -0.72% | -0.43% | -1.06% | 50% |
| first buy after a 20%+ fall (6 months) | 355 | +0.30% | +0.53% | -0.82% | 51% | 166 | -1.30% | -2.54% | -2.35% | 42% |
| first buy, not a 10b5-1 plan | 1686 | +0.24% | +0.66% | +0.89% | 53% | 663 | -0.43% | -0.88% | -1.55% | 44% |
| big stake increase (≥ 25% of holding) | 553 | +0.28% | +1.50% | +1.63% | 57% | 229 | +0.89% | -0.94% | -1.94% | 43% |
