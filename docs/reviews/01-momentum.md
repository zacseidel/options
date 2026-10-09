# Review 1 — `zacseidel/momentum`

Reviewed 2026-10-08 at commit for the 2026-10-06 auto-update. ~6.2k lines of Python;
repo is 885 MB because of generated HTML (12–24 MB each, base64 PNG charts, committed
twice under `reports/` and `docs/reports/`) plus a 50 MB SQLite DB committed to git.

## What it does
Tue/Fri GitHub Action: sync universe from SSGA → fetch Polygon daily bars (free tier,
13 s throttle) → compute several stock-selection lists → render static HTML → GitHub Pages.

## Mapping onto Universe / Category / Method / Evaluation

### Universe (keep, port almost as-is)
- `universe.py`: downloads SPY (S&P 500) and MDY (S&P 400) holdings xlsx from SSGA,
  finds the header row dynamically, normalizes symbol/name/weight, merges GOOG/GOOGL
  for weight-derived cohorts. Polygon does not provide index membership, so this stays.
- `data/universe/change_log.csv`: append-only add/drop log; `backfill_rankmom.members_on()`
  replays it into point-in-time membership. **Only goes back to ~Jan 2026** — a 5-year
  backtest needs historical constituents from another source (survivorship-bias gap).
- Derived universes: megacap = top 25 by SPY weight, "munger" = top 50 by weight,
  SP400 top 15% by MDY weight. These are *universe filters*, not categories.

### Categories (all become pluggable category definitions)
| Current name | Universe | Rule | Picks |
|---|---|---|---|
| Momentum (`megacap`/`sp500`/`sp400`) | each | 12-mo return rank, keep only rank ≤ rank one month ago | top 5 shown / 10 stored |
| Stall flag (overlay) | sp500 picks | no new 60-session closing high in >15 sessions; "isolated" if ≤3 of top 10 stalled → swap to next pick | modifier |
| Mega Cap Laggards | top 10 by weight | worst average of 3/6/12-mo return ranks | 3 |
| Rank Momentum (`rankmom500/400`) | sp500, sp400 | best average of 3/6/12-mo return ranks | 10 |
| Munger | top 50 by weight | close < SMA200 in last 10 sessions AND close > SMA10 | all signals |
| Munger400L | SP400 top 15% by weight | same SMA dip/recover | all |
| Munger400R | SP400 names in top 15% by 12-mo return on any report date in trailing year | same SMA dip/recover | all |
| Industry ranks | SP500+400 | SIC 2-digit groups, cap-weighted 12-mo return, rank & rank change | page |

Reusable pure functions: `_multi_period_scores`, `sessions_since_high`, `assess_stalls`,
`_mean_reversion_signals` (session-calendar SMA with 90% coverage rule),
`rank_industries` / `_cap_weighted_return`, `sic.py`.

### Method
Implicitly **long stock only**. No options anywhere.

### Evaluation
**None.** Only "streak" (consecutive report appearances) and a "dropped" list with
12-mo/1-wk returns. Picks are never scored forward. (A code comment mentions an offline
2-year backtest of the stall rule; it isn't in the repo.) This is the biggest gap the new
project fills.

## Data-layer lessons
- Most of `prices.py` (825 lines) works around free-tier limits: throttle, grouped-daily vs
  per-ticker gap planning, only caching the dates it ranks on, 2-year retention edge cases.
  **Paid plan makes nearly all of this unnecessary.**
- Split repair: `adjusted=true` is relative to fetch time, so cached rows go stale after
  splits; the repo detects "flip-flop" and level-break contamination and refetches.
  **New design: store unadjusted bars + Polygon splits/dividends, adjust on read.**
- Reused tickers (e.g. BNY) needed `history_floors`. **New design: key securities by a stable
  ID (Polygon `composite_figi` / ticker events), not ticker string.**
- VOO rows are used as the trading calendar; `_is_date_in_db` = ">800 rows that day".
  **New: an explicit market calendar table.**

## Don't carry over
- Momentum pick tables store formatted strings (`"12.3%"`) as TEXT.
- One table per cohort with bespoke schemas → replace with one generic signals table
  (strategy, as_of, ticker, rank, score, features JSON).
- Strategy logic interleaved with SQLite reads and "today − 1 day" dates → categories
  should be pure functions of (point-in-time universe, price panel, as_of) so any date
  can be recomputed. That removes the need for HTML-patching backfill scripts
  (`backfill_laggards.py`, `backfill_rankmom.py`).
- Base64 PNG charts and committing DB + reports to git.

## Keep / reuse
- SSGA universe sync + change log + replay.
- Category rules above (as pure functions) and their unit tests (`test_*` offline ones).
- Company metadata (Polygon ticker details: SIC, market cap) + capped refresh logic.
- Chart MA-position dots (10 EMA / 21 EMA / 50 SMA) idea; Polygon news per pick.
- Twice-weekly report + GitHub Pages delivery model (to confirm).
