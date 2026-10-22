# Option method grid

Options history 2024-10-09 → 2026-10-21. Fills at the traded price (mid of the day's open and close), no spread haircut. Regenerate with `python -m market.evaluate.option_grid`.

Exposure is stock-equivalent at entry (1.0× = holding the stock). Half-Kelly is the site's per-trade 0.5 · (win rate − loss rate / payoff); Position = half-Kelly ÷ exposure (cap 100%), the share of a portfolio per position once leverage is counted. LEAP/diagonal windows hold the stock until a qualifying call appears ('no option' = never).

## SPY Ldrs · SI (`mom12si_sp500.top5`, 200 windows)

Tracked picks: **Defensive** Cash-secured put Δ-0.45 (Sharpe 1.40, worst -26%) · **Balanced** LEAP 12m Δ0.60, 50% in calls (Sharpe 1.81, worst -43%) · **Aggressive** LEAP 12m Δ0.60, 100% in calls (Sharpe 1.93, worst -49%)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 125% | 419% | 1.42 | -42% | 18% | 1.00× | 18% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 29% | 68% | 1.18 | -17% | 26% | 0.22× | 100% | 12% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 33% | 78% | 1.08 | -18% | 24% | 0.32× | 75% | 12% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 54% | 142% | 1.40 | -26% | 23% | 0.45× | 51% | 12% | 17 |
| Lower risk | Covered call Δ0.10, ~21d | 101% | 312% | 1.48 | -37% | 18% | 0.88× | 21% | 7% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 86% | 254% | 1.40 | -36% | 19% | 0.80× | 23% | 7% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 77% | 218% | 1.39 | -35% | 19% | 0.70× | 27% | 7% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 63% | 171% | 1.33 | -32% | 19% | 0.60× | 31% | 7% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 50% | 129% | 1.25 | -29% | 18% | 0.50× | 36% | 7% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 112% | 362% | 1.51 | -42% | 19% | 0.74× | 25% | 12% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 103% | 321% | 1.47 | -43% | 19% | 0.62× | 32% | 12% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 111% | 354% | 1.45 | -40% | 19% | 0.74× | 25% | 24% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 98% | 300% | 1.36 | -40% | 19% | 0.62× | 30% | 24% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 141% | 498% | 1.51 | -42% | 18% | 1.00× | 18% | 12% | 210 |
| Same risk | LEAP 6m Δ0.60, match stock | 152% | 552% | 1.50 | -42% | 18% | 1.00× | 18% | 8% | 206 |
| Same risk | LEAP 12m Δ0.80, match stock | 140% | 490% | 1.49 | -40% | 17% | 1.00× | 17% | 24% | 433 |
| Same risk | LEAP 12m Δ0.60, match stock | 160% | 594% | 1.59 | -44% | 19% | 1.00× | 19% | 26% | 411 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 179% | 703% | 1.58 | -42% | 18% | 1.26× | 14% | 12% | 210 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 271% | 1338% | 1.58 | -48% | 17% | 1.64× | 11% | 8% | 206 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 142% | 502% | 1.58 | -36% | 17% | 1.02× | 17% | 24% | 433 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 230% | 1030% | 1.81 | -43% | 19% | 1.33× | 14% | 26% | 411 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 387% | 2393% | 1.37 | -62% | 18% | 2.52× | 7% | 12% | 210 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 663% | 6114% | 1.36 | -72% | 17% | 3.28× | 5% | 8% | 206 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 314% | 1693% | 1.55 | -52% | 17% | 2.04× | 8% | 24% | 433 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 598% | 5084% | 1.93 | -49% | 20% | 2.67× | 7% | 26% | 411 |

## SPY Rank Mom · IV (`rankmomiv_sp500.top5`, 205 windows)

Tracked picks: **Defensive** Cash-secured put Δ-0.20 (Sharpe 1.63, worst -16%) · **Balanced** LEAP 12m Δ0.60, 50% in calls (Sharpe 1.55, worst -40%) · **Aggressive** LEAP 12m Δ0.60, 100% in calls (Sharpe 1.59, worst -55%)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 92% | 277% | 1.26 | -38% | 16% | 1.00× | 16% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 30% | 71% | 1.63 | -16% | 27% | 0.22× | 100% | 11% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 41% | 100% | 1.34 | -19% | 24% | 0.32× | 77% | 11% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 45% | 114% | 1.28 | -21% | 22% | 0.44× | 49% | 11% | 17 |
| Lower risk | Covered call Δ0.10, ~21d | 73% | 206% | 1.26 | -33% | 17% | 0.85× | 20% | 7% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 59% | 157% | 1.14 | -32% | 16% | 0.79× | 20% | 7% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 52% | 133% | 1.11 | -30% | 16% | 0.69× | 22% | 7% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 45% | 114% | 1.09 | -29% | 16% | 0.60× | 26% | 7% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 35% | 85% | 0.99 | -26% | 15% | 0.50× | 30% | 7% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 65% | 177% | 1.22 | -34% | 16% | 0.74× | 21% | 7% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 56% | 148% | 1.18 | -33% | 15% | 0.62× | 25% | 7% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 70% | 193% | 1.15 | -36% | 15% | 0.74× | 20% | 21% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 60% | 160% | 1.07 | -36% | 15% | 0.62× | 25% | 21% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 97% | 297% | 1.30 | -39% | 15% | 1.00× | 15% | 7% | 206 |
| Same risk | LEAP 6m Δ0.60, match stock | 111% | 356% | 1.34 | -40% | 15% | 1.00× | 15% | 5% | 203 |
| Same risk | LEAP 12m Δ0.80, match stock | 111% | 358% | 1.39 | -41% | 16% | 1.00× | 16% | 21% | 434 |
| Same risk | LEAP 12m Δ0.60, match stock | 115% | 374% | 1.42 | -41% | 17% | 1.00× | 17% | 25% | 413 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 107% | 337% | 1.23 | -45% | 15% | 1.34× | 11% | 7% | 206 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 163% | 615% | 1.27 | -54% | 14% | 1.81× | 7% | 5% | 203 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 111% | 356% | 1.43 | -38% | 16% | 1.08× | 15% | 21% | 434 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 154% | 563% | 1.55 | -40% | 18% | 1.42× | 12% | 25% | 413 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 217% | 944% | 1.09 | -68% | 15% | 2.68× | 5% | 7% | 206 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 344% | 1967% | 1.07 | -78% | 14% | 3.62× | 4% | 5% | 203 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 251% | 1179% | 1.47 | -55% | 16% | 2.15× | 7% | 21% | 434 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 334% | 1874% | 1.59 | -55% | 18% | 2.85× | 6% | 25% | 413 |

## MDY Improving Fund. & Rank (`emergingall_sp400.top5`, 268 windows)

Tracked picks: **Defensive** Cash-secured put Δ-0.45 (Sharpe 1.48, worst -7%) · **Balanced** LEAP 6m Δ0.60, match stock (Sharpe 1.35, worst -31%) · **Aggressive** LEAP 6m Δ0.60, 50% in calls (Sharpe 1.23, worst -38%)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 44% | 111% | 1.16 | -30% | 10% | 1.00× | 10% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 11% | 24% | 1.14 | -7% | 23% | 0.24× | 94% | 57% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 12% | 25% | 1.10 | -7% | 21% | 0.31× | 66% | 57% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 17% | 38% | 1.48 | -7% | 23% | 0.43× | 54% | 57% | 17 |
| Lower risk | Covered call Δ0.10, ~21d | 29% | 67% | 0.90 | -28% | 9% | 0.81× | 11% | 38% | 24 |
| Lower risk | Covered call Δ0.20, ~21d | 28% | 66% | 0.91 | -28% | 9% | 0.77× | 11% | 38% | 24 |
| Lower risk | Covered call Δ0.30, ~21d | 22% | 51% | 0.73 | -26% | 8% | 0.69× | 12% | 38% | 24 |
| Lower risk | Covered call Δ0.40, ~21d | 20% | 46% | 0.70 | -25% | 8% | 0.60× | 13% | 38% | 24 |
| Lower risk | Covered call Δ0.50, ~21d | 17% | 38% | 0.59 | -23% | 7% | 0.52× | 14% | 38% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 36% | 86% | 1.05 | -30% | 10% | 0.76× | 13% | 63% | 185 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 32% | 75% | 0.94 | -28% | 9% | 0.67× | 14% | 63% | 185 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 49% | 124% | 1.33 | -26% | 11% | 0.75× | 15% | 76% | 373 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 45% | 113% | 1.26 | -25% | 11% | 0.63× | 18% | 76% | 373 |
| Same risk | LEAP 6m Δ0.80, match stock | 51% | 132% | 1.29 | -31% | 11% | 1.00× | 11% | 63% | 214 |
| Same risk | LEAP 6m Δ0.60, match stock | 56% | 145% | 1.35 | -31% | 12% | 1.00× | 12% | 48% | 218 |
| Same risk | LEAP 12m Δ0.80, match stock | 49% | 125% | 1.25 | -28% | 11% | 1.00× | 11% | 76% | 458 |
| Same risk | LEAP 12m Δ0.60, match stock | 46% | 116% | 1.18 | -29% | 10% | 1.00× | 10% | 77% | 437 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 54% | 141% | 1.18 | -35% | 11% | 1.38× | 8% | 63% | 214 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 73% | 205% | 1.23 | -38% | 11% | 1.86× | 6% | 48% | 218 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 48% | 120% | 1.21 | -29% | 11% | 1.00× | 10% | 76% | 458 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 46% | 117% | 1.10 | -33% | 10% | 1.52× | 7% | 77% | 437 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 82% | 237% | 1.03 | -50% | 11% | 2.75× | 4% | 63% | 214 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 128% | 435% | 1.07 | -58% | 11% | 3.71× | 3% | 48% | 218 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 57% | 152% | 1.11 | -38% | 10% | 2.01× | 5% | 76% | 458 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 51% | 130% | 0.91 | -42% | 9% | 3.04× | 3% | 77% | 437 |

## Mega Laggards (`laggards_mega10.top2.hold21`, 424 windows)

Tracked picks: **Defensive** Diagonal 6m Δ0.80 / short Δ0.30 (Sharpe 1.47, worst -13%) · **Balanced** LEAP 6m Δ0.80, match stock (Sharpe 1.54, worst -18%) · **Aggressive** LEAP 6m Δ0.80, 50% in calls (Sharpe 1.46, worst -34%)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 51% | 131% | 1.51 | -19% | 23% | 1.00× | 23% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 13% | 29% | 1.19 | -6% | 36% | 0.22× | 100% | 0% | 38 |
| Lower risk | Cash-secured put Δ-0.30 | 17% | 38% | 1.25 | -8% | 32% | 0.31× | 100% | 0% | 35 |
| Lower risk | Cash-secured put Δ-0.45 | 23% | 53% | 1.38 | -10% | 29% | 0.45× | 65% | 0% | 38 |
| Lower risk | Covered call Δ0.10, ~21d | 45% | 111% | 1.49 | -17% | 23% | 0.90× | 26% | 0% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 38% | 93% | 1.45 | -15% | 24% | 0.80× | 29% | 0% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 33% | 80% | 1.43 | -14% | 24% | 0.70× | 34% | 0% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 28% | 64% | 1.33 | -13% | 24% | 0.60× | 40% | 0% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 23% | 53% | 1.29 | -11% | 25% | 0.50× | 50% | 0% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 37% | 89% | 1.50 | -14% | 21% | 0.75× | 28% | 0% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 31% | 72% | 1.47 | -13% | 21% | 0.62× | 34% | 0% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 36% | 88% | 1.45 | -14% | 21% | 0.75× | 28% | 0% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 30% | 71% | 1.40 | -12% | 21% | 0.62× | 34% | 0% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 52% | 133% | 1.54 | -18% | 21% | 1.00× | 21% | 0% | 199 |
| Same risk | LEAP 6m Δ0.60, match stock | 50% | 129% | 1.45 | -18% | 20% | 1.00× | 20% | 0% | 197 |
| Same risk | LEAP 12m Δ0.80, match stock | 51% | 130% | 1.50 | -17% | 21% | 1.00× | 21% | 0% | 409 |
| Same risk | LEAP 12m Δ0.60, match stock | 50% | 128% | 1.44 | -18% | 21% | 1.00× | 21% | 0% | 408 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 103% | 321% | 1.46 | -34% | 20% | 2.03× | 10% | 0% | 199 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 147% | 526% | 1.32 | -46% | 18% | 2.85× | 6% | 0% | 197 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 73% | 204% | 1.44 | -26% | 20% | 1.51× | 13% | 0% | 409 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 103% | 320% | 1.39 | -35% | 19% | 2.05× | 9% | 0% | 408 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 253% | 1197% | 1.32 | -61% | 19% | 4.05× | 5% | 0% | 199 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 365% | 2165% | 1.10 | -77% | 18% | 5.70× | 3% | 0% | 197 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 167% | 638% | 1.34 | -48% | 19% | 3.02× | 6% | 0% | 409 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 247% | 1155% | 1.24 | -62% | 18% | 4.11× | 4% | 0% | 408 |
