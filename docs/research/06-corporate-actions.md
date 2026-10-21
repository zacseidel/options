# Corporate actions → forward returns

_Generated 2026-10-21 by `python -m market.research.corporate_actions`._

> **Outcome (2026-10-21).** Dividend raises ≥ 10% beat the *average* S&P 500 / 400 member in both
> halves. As a strategy (one lot per raise, held 126 sessions, total return with dividends) they matched
> SPY since 2021-11 (12.2% vs 12.1% a year; worst drop −21% vs −24%) and far beat the S&P 400 (MDY 6.1%).
> Kept as the Lab category Dividend Raisers (user's call). Dividend cuts ≥ 10% lagged badly: an input
> for the shorts phase. Declaration dates are now stored with the dividends.

2,753 events at S&P 500 / 400 members, 2021-11-15 → 2026-10-20; 99% of dividends carry a declaration date. In-sample before 2025-01-01. Mean excess return vs the average S&P 500 / 400 member over the same window.

| Event | n in | 21d | 63d | 126d | 252d | hit 126d | n out | 21d | 63d | 126d | 252d | hit 126d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dividend initiation | 17 | +0.71% | -4.75% | -5.44% | +5.59% | 35% | 10 | -2.05% | -1.32% | +10.49% | +125.51% | 22% |
| raise ≥ 5% | 1135 | -0.04% | +0.26% | +1.14% | +0.98% | 51% | 622 | +0.15% | +0.53% | +0.95% | +0.25% | 45% |
| raise ≥ 10% | 592 | +0.38% | +0.82% | +2.01% | +2.63% | 52% | 322 | -0.27% | +1.85% | +3.47% | +3.55% | 48% |
| raise ≥ 20% | 167 | +0.08% | -0.11% | -0.20% | -0.04% | 46% | 62 | -0.12% | +5.05% | +12.65% | +4.36% | 58% |
| raise < 5% | 430 | -0.51% | -1.15% | -1.25% | -2.10% | 43% | 331 | +0.03% | -0.35% | -1.30% | -5.10% | 44% |
| cut ≥ 10% | 62 | -2.03% | -1.50% | -6.10% | -7.88% | 40% | 20 | +0.26% | -4.09% | -11.69% | -31.45% | 35% |
| special dividend | 87 | -0.72% | -1.54% | -0.85% | -2.96% | 44% | 20 | +3.56% | -0.70% | -4.86% | -11.65% | 35% |
| spinoff (new company) | 8 | +1.24% | +2.29% | +18.17% | +37.13% | 62% | 5 | -8.09% | -6.05% | +52.94% | — | 100% |
