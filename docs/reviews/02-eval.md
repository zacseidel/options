# Review 2 — `zacseidel/eval`

Reviewed 2026-10-08 (data through 2026-10-05). ~2.2k lines Python + ~800 lines vanilla JS,
~2k lines of tests. Small repo (6 MB): scraped report JSON, per-ticker price-cache JSON,
processed JSON consumed by a static Chart.js site on GitHub Pages.

## What it does
Tue/Fri GitHub Action, 2 hours after `momentum`: **scrapes the momentum HTML reports**
(BeautifulSoup, `parser_version` bumps when sections change) → turns each report's
lists into trades → simulates equal-weight portfolios vs SPY → writes
`signals.json`, `positions.json`, `strategy_returns.json`, `manifest.json`.

## This is the "Evaluation" layer — and part of "Method"

### Strategy = section + slot + exit rule (16 today)
| Exit model | Strategies | Rule |
|---|---|---|
| rank membership (same-session) | sp500/megacap/sp400 top5 & next5 | hold while listed in ranks 1–5 (or 6–10); exit at first session on/after the report that drops it |
| `rank_next_session` | rankmom500/400 top5 & next5 | exit the session *after* the drop report; relisting before it trades cancels the sale |
| `ema21` | munger, munger400l, munger400r | enter while flat; exit next session after a close below 21-day EMA |
| `sma10` (direction) | industry_up5 (below), industry_down5 (above) | next-session exit when close crosses 10-day SMA |
| `hold21` | megalaggards2 | new lot every listing, sell 21 sessions after entry; lots stack |

So "Method" really has two parts: **instrument** (today only long stock) and
**position rules** (entry condition, exit rule, lot stacking, slot selection). The
SMA10/EMA21 *variants* of the rank strategies were tested then deleted in 2026-09; in the
new system variants should stay evaluated in the background and simply be hidden.

### Execution & portfolio conventions (keep — these are good)
- Signals are known before the open; entry = first session on/after signal date.
- Fill price = day **VWAP**, fallback (open+close)/2, fallback close.
- Technical exits are decided on a completed close and executed the **next** session
  (no look-ahead).
- Portfolio: start NAV 100, equal weight per open trade, rebalance only on trade-event
  days, mark daily at close. SPY benchmark on the same basis.
- `--as-of` deterministic rebuild; `manifest.json` records rule text, versions, input
  hashes, data-through date.
- `validate_positions()` invariants: unique trade ids, every trade traces to a signal,
  no weekend/future dates, exit after entry, technical exit actually triggered,
  no overlapping trades per ticker (except stacked-lot strategies). → port as the
  backtest engine's assertion suite.

### Metrics (the "standard evaluation" seed)
- Trailing 12-mo return (or since inception), rolling 3-mo return, both vs SPY.
- Sharpe: daily log returns, 5% annual risk-free rate, √252; 12-mo needs ≥200 obs,
  inception ≥40.
- Closed-trade stats: win %, loss %, avg win / avg loss, payoff ratio.
- Half-Kelly `0.5·max(0, p − q/b)` with a 20-closed-trade minimum; for stacked lots also
  `independent_run_count` (merges overlapping lots) because lot outcomes are correlated.

### Current results (Jan 7 → Oct 5 2026, price return, NAV from 100; SPY = 112.4)
sp500_top5 228.5 · rankmom500_top5 213.1 · sp400 top5 166.5 · megacap_top5 158.0 ·
rankmom500_next5 151.5 · megalaggards2 140.3 · sp500_next5 129.8 · munger 114.6 ·
rankmom400_next5 106.1 · rankmom400_top5 95.0 · megacap_next5 94.3 · sp400_next5 81.1.
(munger400l/r and industry cards are only 1–2 months old.) Nine months of live signals is
a thin sample — the main argument for a real 5-year backtest.

## Gaps the new project should close
1. **Coupling by scraping HTML.** The evaluator re-parses rendered reports. New system: the
   evaluator reads the shared signals table directly; no scraper.
2. **Forward-only history.** Only report dates since Jan 2026 exist. With 5-year Polygon
   data and point-in-time category functions we can backtest every category from 2021 —
   *subject to historical index membership* (see review 1).
3. **Price return only.** No dividends, fees, slippage. Paid Polygon gives dividends → total
   return. Options methods need a bid/ask cost model or results will be badly optimistic.
4. **Long stock only.** No CSP / covered call / LEAP simulation; those need option chains,
   historical option prices, and rules for expiry, assignment, rolls.
5. **Per-ticker JSON price cache + 12.5 s throttle** → replace with the shared price store.
   Note the bug class it fixed: Polygon bar timestamps must be converted carefully
   (they were shifting dates in UTC); use America/New_York session dates.
6. **One portfolio sizing policy.** Equal weight only; Kelly is reported, not applied.

## Keep / reuse
- Position-lifecycle simulator and exit-model taxonomy (generalize to a rule registry).
- Execution-price and no-look-ahead conventions.
- NAV builder, metric functions, half-Kelly, independent-run count.
- `validate_positions` invariants + the offline unit tests in `tests/test_process.py`.
- Manifest/audit idea and `--as-of` rebuilds.
- Frontend pattern: no-build vanilla JS + Chart.js reading static JSON; sortable strategy
  cards; positions table; NAV and rolling-3M charts vs SPY.
