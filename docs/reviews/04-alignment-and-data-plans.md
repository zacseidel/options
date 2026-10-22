# Review 04 — Strategies ↔ Newsfeed alignment, the SPY Sharpe, and whether the paid plans are needed (2026-10-22)

Read-only review; nothing in the code was changed. Numbers are from `data/market.duckdb` as of the 2026-10-21 close.

## 1. Strategies page vs Newsfeed "lists considered"

**What happens now**
- The Strategies page (`site/js/app.js` `overview()`) lists `META.strategies` with Lab strategies removed (`isLab`, ~line 1090).
  Lab strategies show only on `#/lab`.
- The Newsfeed candidates are a hand-written list in `config.yaml → newsfeed.candidates` (5 entries). Four of the five are
  Lab strategies (`mom12si_sp500.top5`, `rankmomiv_sp500.top5`, `emergingall_sp400.top5`, `steady_sp500.top5`), so they
  never appear on the Strategies page. Only `laggards_mega10.top2.hold21` is on both.
- Inclusion is "Sharpe > SPY's Sharpe on the same dates" (no 10% margin), and only over that hand-picked list. Strategies
  that would pass the same test (for example `fmom_sp500.top5`) are never considered.

**Proposed design**
1. **One strategies table.** Show every stock strategy, tracked and Lab, on `#/strategies`, with a Stage badge and an
   All / Tracked / Lab filter. Add the columns "SPY Sharpe (same dates)", "Sharpe ÷ SPY" and "In the feed". The Lab page
   keeps its out-of-sample (`since_added`) view.
2. **Rule-based feed.** Drop `newsfeed.candidates`. A strategy is in the feed when all of these hold:
   - it is a stock strategy;
   - its hold rule is `while_listed` or `fixed_hold` (the feed can't express `price_exit`, `short` or `overlay` yet);
   - its half-Kelly is > 0 (this already requires ≥ 20 closed trades);
   - its Sharpe is ≥ 1.10 × SPY's Sharpe over the comparison window (§2).
3. **Move base/filter metadata onto the category.** The "shown with its full base list" display needs the base and filter
   of each list. Today that pairing lives in the config. Declare it on the category instead, e.g.
   `@category(..., base="mom12_sp500", filter="short_interest")`, so any strategy that qualifies gets it.
4. **Hysteresis (recommended).** Enter at ≥ 1.10×, leave below 1.00×. `mom12si_sp500.top5` sits at 1.106× since
   inception and would otherwise flip in and out between runs.
5. **Near-duplicate lists.** Several S&P 500 momentum variants can qualify together (Leaders, Stall, Reasonable Growth,
   SI filter, IV filter, Rank Momentum). The allocator already sizes a shared stock once, at the lowest half-Kelly, so
   this is safe. But the feed gets long and leans heavily on one factor. Option: allow only the best variant per base
   universe and family.
6. **"Changes from the previous week."** Reports are Tue/Fri, so the feed shows two change sets a week. If a weekly view
   is wanted, roll Tue + Fri into one card. The engine can stay as it is.

## 2. Two SPY Sharpes (0.48 vs ~0.99)

They are the same series measured over different dates:

| Where | What it measures | Value |
|---|---|---|
| Strategies page, SPY benchmark row, "Since inception" | `bench.SPY` NAV from its own first date, **2021-10-19**. `benchmark_navs()` starts at the earliest strategy start, which became 2021-10 when the Lab fundamentals strategies `fmom_*` / `shrinkers_*` were added. That window includes the 2022 bear market. | **0.48** |
| Newsfeed "SPY Sharpe, same dates" | SPY over each candidate's own dates (`export_newsfeed.build`, recomputed there) | 0.99 from 2022-11-29; 0.65 from 2024-11-12; 1.08 from 2023-04-25 |
| Strategies page "vs SPY" CAGR column | Already same-dates (`excess_cagr`, computed in the engine) | — |

So the Strategies page mixes same-dates CAGR with a single all-history SPY Sharpe row.

**The larger problem: the result depends on the window.** Each strategy is compared against SPY over its own start
date, so a strategy that began in late 2024 is graded against a weak SPY stretch (0.65), while one that began in late 2022
faces 0.99. Same test, different bar:

| Comparison window | SPY Sharpe | Stock strategies at ≥ 1.10 × SPY |
|---|---|---|
| Each strategy since its own inception (today's newsfeed method) | 0.48 – 1.30 | rankmomiv 1.99×, mom12iv 1.58×, emergingall 1.23×, fmom_sp500 1.21×, mom12si 1.11× |
| Common window since 2024-11-12 (≈ 2 years, every list has data) | 0.65 | 16 strategies, including plain S&P 500 Leaders 1.56× and Rank Momentum 1.85× |
| Trailing 3 years (lists younger than 3 years excluded) | 1.17 | Megacap Laggards 1.29×, S&P 500 Leaders SI filter 1.14× |

The IV-filtered lists look strong mainly because of their window, not the filter. Over identical dates (since 2024-11-12):
- Rank Momentum with the IV filter: Sharpe 1.29, versus 1.20 without it.
- S&P 500 Leaders with the IV filter: 1.02, versus 1.01 without it.

**Proposed fix**
- Store `benchmark_sharpe` (and `benchmark_max_drawdown`) in `metrics.performance()` whenever a benchmark is passed. The
  engine already passes SPY reindexed to the strategy's dates.
- The Strategies page and the newsfeed both read that stored value. The newsfeed stops recomputing it, which leaves one
  definition.
- Either drop the SPY benchmark row from "Since inception", or relabel it "SPY since 2021-10-19 (earliest strategy start)".
  On the 3Y / 1Y windows the single SPY row is correct as is.
- **Decide the comparison window for the 10% rule:**
  - (a) Common trailing 2 years: one SPY number, every list compared on identical dates. This is the fairest, but SPY's
    Sharpe is low there, so the feed gets long.
  - (b) Trailing 3 years: strict, and excludes the young lists.
  - (c) Since inception: today's method, which is window-biased.

  Recommendation: **(a) with the 10% margin plus hysteresis**, or (a) with a higher margin such as 1.25×, if a shorter
  feed is wanted.

## 3. Do we need Stocks Starter and Options Starter ($29 + $29 a month)?

### What the pipeline calls (from code and `fetch_log`, steady state)

| Need | Endpoint | Calls | Plan feature it relies on |
|---|---|---|---|
| Daily bars | `/v2/aggs/grouped/.../stocks/{date}` | 1/day | none (EOD) |
| Splits + dividends, last 60 days | `/v3/reference/splits`, `/dividends`, market-wide pages | ~36/day | none |
| Splits + dividends, **full window weekly** | per ticker | **3,392/week** | unlimited calls |
| Market caps, quarter-end anchors | `/v3/reference/tickers/{t}?date=` | ~503/quarter | unlimited calls |
| New names / gaps / ticker lookups | ticker range, `/vX/.../events`, `/v3/reference/tickers` | ~10–20/day (bursts on new signals) | 5-year history only if a gap is >2 years old |
| 13F period pricing | grouped daily, adjusted | ~0–40/day, bursty | none |
| Short interest | `/stocks/v1/short-interest` | 1/day (backfill: 1 per ticker) | — |
| **Option panel** (12 tracked option methods) | OPRA day-aggregate **flat files** | 1 file/day, ~19k contract-rows kept | **Options Starter flat files** |
| **Option flow** (IV filter lists, IV warnings, ivinverted) | same file, summarized for 1,457 names | 0 extra | **Options Starter flat files** |

### Probe of the old `POLYGON_API_KEY` (2026-10-22)

| Result | Endpoints |
|---|---|
| OK | Stocks grouped daily, including 2024-06-03 (more than 2 years back); ticker ranges; splits; dividends; ticker details as of a date; ticker events; short interest (back to 2017); option contracts; option per-contract daily bars; **option chain snapshot with greeks, IV, open interest and the day's OHLC**. |
| Not available on any plan | There is no grouped-daily endpoint for options (400: market type must be stocks/fx/crypto). The only "whole chain in one call" is the per-underlying snapshot: up to 250 contracts a page, current day only. |
| Rate limit | A burst of 7 calls in under a minute was **not** throttled. |

⚠️ The greeks/IV snapshot working, the >2-year history working and the missing rate limit all contradict published Basic
limits. That suggests this key now belongs to the paid account, or that the tiers have changed. **Check the plan behind
that key on the Massive dashboard before relying on this probe.** The assessment below assumes published Basic limits:
5 calls/min, about 2 years of history, end-of-day data, no flat files.

### Stocks Starter → Basic: workable with modest code changes
- Daily steady state is ~50–60 calls, about 10–12 minutes at 5/min.
- Required changes:
  - Add a 5/min throttle to `market.data.polygon.Polygon`. Today it fires up to 16 requests at once.
  - Replace the weekly full-window per-ticker corporate-actions refresh (3,392 calls, about 11 hours at 5/min). The daily
    market-wide 60-day pages already catch new actions going forward.
  - Spread the quarterly market-cap anchors (~100 minutes), or derive caps from shares outstanding × close.
- Lost:
  - Full rebuilds that re-fetch history older than 2 years. History back to 2021 is already stored, so this matters only
    if the database is lost. Back it up.
  - Fast backfills when the universe grows.
- **Risk:** Basic is "end of day", and its publish time may be later than 17:30 ET. The evening run computes the next
  report from tonight's close. Test the free key's same-day grouped bar at 17:30 before switching.
- Saves $29/month ($348/year).

### Options Starter → Basic: possible only by giving things up
- **Option flow can't be rebuilt on Basic.** It needs every chain for 1,457 names every day. Through snapshots that is
  thousands of paginated calls a day, far past 5/min. Losing it drops:
  - the IV-filter lists (two of them in the feed);
  - the IV warning column;
  - `ivinverted_sp900`.

  Evidence that this is cheap to lose: on identical dates the IV filter adds about +0.09 Sharpe to Rank Momentum and
  nothing to S&P 500 Leaders. Replace the IV lists in the feed with their base lists.
- **Tracked option methods could run forward-only on snapshots.** About 47 entry days in 90 days and about 6 new legs a
  day. That needs one or two filtered snapshot pages per selection plus marks on open legs: roughly 20–40 calls a day.
  It is feasible but new engineering: a second data path, snapshot IVs instead of the engine's own IVs, and point-in-time
  data that can't be re-fetched if a day is missed. Per-contract daily bars can patch gaps.
- **Recommended middle path: subscribe on demand.**
  - Pause Options Starter and freeze the option strategies and the Options page at their last data date.
  - Re-subscribe for one month when you want to re-run the grid or research, or bring the option strategies up to date.
    `option_panel` already re-streams only missing sessions (`option_coverage`), and flat files cover 2 years back at any
    time.
  - About $29 × 2–4 months a year, versus $348.
- Keep Options Starter only if the option methods (Options page) and IV lists are things you act on week to week.

### Bottom line
| Choice | Annual cost | You keep | You give up / must build |
|---|---|---|---|
| Both Starter (today) | $696 | everything, with fast rebuilds | — |
| Stocks Basic + Options Starter | $348 | everything | throttle, corporate-actions redesign, check EOD timing |
| Stocks Starter + Options on demand | ~$406–464 | stocks unchanged; options refreshed in batches | IV lists in the feed (swap for base lists); live option tracking |
| **Both Basic + Options on demand** | ~$58–116 | all stock lists, feed, Congress/13F, fundamentals (EDGAR), short interest | IV lists; live option tracking; the stocks-side changes above |

**Recommendation:**
1. Verify which plan the `POLYGON_API_KEY` key is on, and its 17:30 data timing.
2. Then go to **Stocks Basic + Options on demand**.
3. Make the feed's lists come from the rule in §1–2, which will not include the IV lists.
