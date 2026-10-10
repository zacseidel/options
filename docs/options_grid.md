# Option method grid

Options history 2024-10-09 → 2026-10-08. Fills at the traded price (mid of the day's open and close), no spread haircut. Regenerate with `python -m market.evaluate.option_grid`.

Exposure is stock-equivalent at entry (1.0× = holding the stock). Half-Kelly is the site's per-trade 0.5 · (win rate − loss rate / payoff); Position = half-Kelly ÷ exposure (cap 100%), the share of a portfolio per position once leverage is counted. LEAP/diagonal windows hold the stock until a qualifying call appears ('no option' = never).

## mom12_sp500.top5 (`mom12_sp500.top5`, 167 windows)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 101% | 305% | 1.23 | -44% | 16% | 1.00× | 16% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 34% | 78% | 1.34 | -20% | 25% | 0.22× | 100% | 10% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 36% | 84% | 1.17 | -22% | 22% | 0.32× | 69% | 10% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 50% | 124% | 1.29 | -25% | 20% | 0.45× | 44% | 10% | 17 |
| Lower risk | Covered call Δ0.10, ~21d | 85% | 242% | 1.31 | -38% | 16% | 0.87× | 19% | 5% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 77% | 213% | 1.29 | -37% | 16% | 0.79× | 21% | 5% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 71% | 193% | 1.32 | -34% | 16% | 0.69× | 23% | 5% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 57% | 145% | 1.22 | -31% | 16% | 0.60× | 27% | 5% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 44% | 108% | 1.12 | -27% | 15% | 0.50× | 31% | 5% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 102% | 309% | 1.41 | -43% | 17% | 0.74× | 23% | 10% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 94% | 273% | 1.37 | -43% | 17% | 0.62× | 28% | 10% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 101% | 302% | 1.36 | -41% | 17% | 0.74× | 23% | 25% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 96% | 283% | 1.35 | -40% | 17% | 0.62× | 28% | 25% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 115% | 360% | 1.31 | -45% | 15% | 1.00× | 15% | 10% | 210 |
| Same risk | LEAP 6m Δ0.60, match stock | 127% | 415% | 1.33 | -45% | 16% | 1.00× | 16% | 6% | 206 |
| Same risk | LEAP 12m Δ0.80, match stock | 116% | 367% | 1.32 | -43% | 15% | 1.00× | 15% | 25% | 441 |
| Same risk | LEAP 12m Δ0.60, match stock | 129% | 424% | 1.39 | -46% | 17% | 1.00× | 17% | 28% | 415 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 137% | 460% | 1.31 | -46% | 15% | 1.27× | 12% | 10% | 210 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 217% | 900% | 1.38 | -51% | 16% | 1.64× | 10% | 6% | 206 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 114% | 357% | 1.35 | -40% | 15% | 1.02× | 15% | 25% | 441 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 166% | 606% | 1.49 | -46% | 17% | 1.31× | 13% | 28% | 415 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 305% | 1534% | 1.20 | -70% | 16% | 2.55× | 6% | 10% | 210 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 534% | 3887% | 1.24 | -74% | 17% | 3.28× | 5% | 6% | 206 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 242% | 1064% | 1.36 | -56% | 16% | 2.04× | 8% | 25% | 441 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 365% | 2046% | 1.54 | -57% | 18% | 2.61× | 7% | 28% | 415 |

## rankmom_sp500.top5 (`rankmom_sp500.top5`, 174 windows)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 82% | 231% | 1.14 | -39% | 16% | 1.00× | 16% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 30% | 68% | 1.80 | -10% | 28% | 0.22× | 100% | 9% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 42% | 102% | 1.44 | -15% | 27% | 0.31× | 85% | 9% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 46% | 112% | 1.32 | -18% | 23% | 0.45× | 52% | 9% | 18 |
| Lower risk | Covered call Δ0.10, ~21d | 64% | 167% | 1.14 | -33% | 16% | 0.88× | 18% | 6% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 58% | 148% | 1.13 | -30% | 16% | 0.79× | 20% | 6% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 53% | 135% | 1.18 | -28% | 16% | 0.70× | 24% | 6% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 44% | 107% | 1.11 | -27% | 17% | 0.60× | 28% | 6% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 38% | 90% | 1.10 | -22% | 18% | 0.50× | 36% | 6% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 78% | 215% | 1.41 | -31% | 16% | 0.74× | 22% | 9% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 74% | 203% | 1.51 | -28% | 17% | 0.62× | 27% | 9% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 80% | 224% | 1.30 | -36% | 17% | 0.74× | 23% | 24% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 74% | 204% | 1.33 | -35% | 17% | 0.62× | 27% | 24% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 91% | 262% | 1.18 | -40% | 15% | 1.00× | 15% | 9% | 210 |
| Same risk | LEAP 6m Δ0.60, match stock | 108% | 331% | 1.29 | -42% | 15% | 1.00× | 15% | 6% | 203 |
| Same risk | LEAP 12m Δ0.80, match stock | 96% | 281% | 1.22 | -43% | 16% | 1.00× | 16% | 24% | 425 |
| Same risk | LEAP 12m Δ0.60, match stock | 101% | 305% | 1.28 | -41% | 18% | 1.00× | 18% | 27% | 409 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 90% | 262% | 1.04 | -45% | 14% | 1.35× | 10% | 9% | 210 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 143% | 486% | 1.13 | -53% | 13% | 1.87× | 7% | 6% | 203 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 97% | 286% | 1.27 | -40% | 15% | 1.08× | 14% | 24% | 425 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 126% | 411% | 1.34 | -42% | 18% | 1.46× | 12% | 27% | 409 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 150% | 523% | 0.84 | -69% | 14% | 2.70× | 5% | 9% | 210 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 266% | 1232% | 0.92 | -80% | 14% | 3.74× | 4% | 6% | 203 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 190% | 736% | 1.22 | -59% | 15% | 2.15× | 7% | 24% | 425 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 225% | 952% | 1.24 | -62% | 17% | 2.92× | 6% | 27% | 409 |

## mom12_megacap.top5 (`mom12_megacap.top5`, 217 windows)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 43% | 104% | 0.82 | -36% | 8% | 1.00× | 8% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 18% | 39% | 0.93 | -11% | 16% | 0.21× | 76% | 0% | 17 |
| Lower risk | Cash-secured put Δ-0.30 | 28% | 65% | 0.97 | -23% | 13% | 0.31× | 40% | 0% | 17 |
| Lower risk | Cash-secured put Δ-0.45 | 30% | 68% | 0.88 | -25% | 9% | 0.45× | 21% | 0% | 17 |
| Lower risk | Covered call Δ0.10, ~21d | 33% | 78% | 0.75 | -32% | 7% | 0.90× | 8% | 0% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 28% | 65% | 0.71 | -29% | 7% | 0.80× | 9% | 0% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 26% | 57% | 0.71 | -25% | 7% | 0.70× | 11% | 0% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 22% | 50% | 0.69 | -22% | 8% | 0.60× | 13% | 0% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 20% | 45% | 0.71 | -20% | 9% | 0.50× | 17% | 0% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 26% | 60% | 0.65 | -28% | 6% | 0.75× | 8% | 0% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 23% | 51% | 0.62 | -25% | 6% | 0.62× | 9% | 0% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 36% | 85% | 0.82 | -30% | 8% | 0.74× | 11% | 3% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 31% | 72% | 0.80 | -26% | 8% | 0.62× | 13% | 3% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 42% | 101% | 0.80 | -35% | 7% | 1.00× | 7% | 0% | 204 |
| Same risk | LEAP 6m Δ0.60, match stock | 48% | 119% | 0.85 | -39% | 8% | 1.00× | 8% | 0% | 199 |
| Same risk | LEAP 12m Δ0.80, match stock | 50% | 125% | 0.90 | -37% | 9% | 1.00× | 9% | 3% | 416 |
| Same risk | LEAP 12m Δ0.60, match stock | 50% | 124% | 0.88 | -40% | 9% | 1.00× | 9% | 1% | 413 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 55% | 139% | 0.78 | -43% | 7% | 1.75× | 4% | 0% | 204 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 77% | 213% | 0.78 | -52% | 7% | 2.47× | 3% | 0% | 199 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 56% | 142% | 0.92 | -36% | 8% | 1.33× | 6% | 3% | 416 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 66% | 175% | 0.89 | -42% | 8% | 1.82× | 5% | 1% | 413 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 91% | 265% | 0.64 | -69% | 7% | 3.50× | 2% | 0% | 204 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 122% | 393% | 0.59 | -76% | 7% | 4.95× | 1% | 0% | 199 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 99% | 297% | 0.83 | -56% | 8% | 2.66× | 3% | 3% | 416 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 107% | 327% | 0.72 | -64% | 8% | 3.64× | 2% | 1% | 413 |

## laggards_mega10.top2.hold21 (`laggards_mega10.top2.hold21`, 416 windows)

| Group | Method | CAGR | Total | Sharpe | Worst drop | Half-Kelly | Exposure | Position | No option | DTE |
|---|---|---|---|---|---|---|---|---|---|---|
| Stock | Stock (same windows) | 51% | 129% | 1.51 | -19% | 23% | 1.00× | 23% | — | — |
| Lower risk | Cash-secured put Δ-0.20 | 13% | 29% | 1.20 | -6% | 36% | 0.22× | 100% | 0% | 38 |
| Lower risk | Cash-secured put Δ-0.30 | 17% | 37% | 1.26 | -8% | 32% | 0.31× | 100% | 0% | 35 |
| Lower risk | Cash-secured put Δ-0.45 | 24% | 53% | 1.40 | -10% | 29% | 0.45× | 65% | 0% | 38 |
| Lower risk | Covered call Δ0.10, ~21d | 45% | 110% | 1.50 | -17% | 23% | 0.90× | 26% | 0% | 21 |
| Lower risk | Covered call Δ0.20, ~21d | 39% | 93% | 1.47 | -15% | 24% | 0.80× | 30% | 0% | 21 |
| Lower risk | Covered call Δ0.30, ~21d | 34% | 80% | 1.46 | -14% | 24% | 0.70× | 34% | 0% | 21 |
| Lower risk | Covered call Δ0.40, ~21d | 28% | 64% | 1.36 | -13% | 24% | 0.60× | 40% | 0% | 21 |
| Lower risk | Covered call Δ0.50, ~21d | 24% | 53% | 1.33 | -11% | 25% | 0.50× | 50% | 0% | 21 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.20 | 38% | 89% | 1.54 | -14% | 21% | 0.75× | 29% | 0% | 24 |
| Lower risk | Diagonal 6m Δ0.80 / short Δ0.30 | 31% | 73% | 1.52 | -13% | 21% | 0.62× | 34% | 0% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.20 | 37% | 87% | 1.48 | -14% | 22% | 0.75× | 29% | 0% | 24 |
| Lower risk | Diagonal 12m Δ0.80 / short Δ0.30 | 31% | 71% | 1.44 | -12% | 21% | 0.62× | 34% | 0% | 24 |
| Same risk | LEAP 6m Δ0.80, match stock | 52% | 131% | 1.55 | -18% | 22% | 1.00× | 22% | 0% | 199 |
| Same risk | LEAP 6m Δ0.60, match stock | 50% | 125% | 1.45 | -18% | 20% | 1.00× | 20% | 0% | 198 |
| Same risk | LEAP 12m Δ0.80, match stock | 51% | 127% | 1.50 | -17% | 22% | 1.00× | 22% | 0% | 408 |
| Same risk | LEAP 12m Δ0.60, match stock | 51% | 127% | 1.46 | -18% | 21% | 1.00× | 21% | 0% | 406 |
| Higher risk | LEAP 6m Δ0.80, 50% in calls | 103% | 310% | 1.45 | -34% | 20% | 2.03× | 10% | 0% | 199 |
| Higher risk | LEAP 6m Δ0.60, 50% in calls | 145% | 497% | 1.30 | -46% | 18% | 2.88× | 6% | 0% | 198 |
| Higher risk | LEAP 12m Δ0.80, 50% in calls | 72% | 196% | 1.43 | -26% | 20% | 1.52× | 13% | 0% | 408 |
| Higher risk | LEAP 12m Δ0.60, 50% in calls | 102% | 306% | 1.37 | -35% | 19% | 2.06× | 9% | 0% | 406 |
| Higher risk | LEAP 6m Δ0.80, 100% in calls | 253% | 1141% | 1.32 | -61% | 20% | 4.06× | 5% | 0% | 199 |
| Higher risk | LEAP 6m Δ0.60, 100% in calls | 359% | 1995% | 1.09 | -77% | 18% | 5.76× | 3% | 0% | 198 |
| Higher risk | LEAP 12m Δ0.80, 100% in calls | 166% | 604% | 1.33 | -48% | 20% | 3.03× | 6% | 0% | 408 |
| Higher risk | LEAP 12m Δ0.60, 100% in calls | 246% | 1089% | 1.23 | -62% | 19% | 4.13× | 5% | 0% | 406 |
