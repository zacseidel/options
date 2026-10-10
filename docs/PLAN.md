# Plan — unified stock & options research system

Draft 3 · 2026-10-09 · inputs: `docs/reviews/01-momentum.md`, `02-eval.md`, `03-smartmoney.md`
Edit freely. Each `▸ DEFAULT` marks a choice you can change; open questions are in §13.

---

## Status (2026-10-09, late evening)

| Area | State |
|---|---|
| Data | S&P 500/400 security master (FIGI ids, ticker history, stand-ins) + Congress-bought and 13F-signal names ("signals" universe, ~1,750 securities); bars self-heal gaps (Honeywell pre-2026, Fiserv 2023–25 were missing); splits/dividends; quarterly market caps |
| Categories | Momentum: S&P 500 / S&P 400 / Megacap Leaders, S&P 500 / S&P 400 Rank Momentum (3/6/12 and Fast 1/3/6) · Reversion: Megacap Laggards, Munger Dip · Congress: Top-5 Buys, Top-5 Holdings (from 2025-01) · Hedge funds: Skilled-Fund Buys, Alpha Drivers (from mid-2025) |
| Smart money | Point-in-time member and fund rankings recomputed from the raw ledgers (`market.smartmoney`); 13F follow-the-filing periods priced once and stored (`fund_periods`); leaderboards per report date (`entity_scores`) |
| Options | Option panel (`option_bars`, ~6.1M rows, ~60 MB) for 166 names, kept only around held windows, 2024-10-08 → now; daily step `options` |
| Evaluation | 22 stock strategies + 12 tracked option strategies (3 per base: Defensive / Balanced / Aggressive, picked from a 25-method grid, `market.evaluate.option_grid`), filled at the traded price and compared with the stock over the same windows |
| Site | Overview, Reports, **Options** (separate page; option strategies kept off the main lists) (grouped by section, with Congress / 13F digests), Strategies, Categories, Congress, Hedge funds, Stocks, Methodology |
| Ops | `python -m market.ops.run` daily: disclosures (House/Senate PTRs + EDGAR daily 13F index) → bars → fund periods → signals → … → export; launchd files in `ops/launchd/` (not yet installed) |
| Next | Re-run the option grid periodically; publish; port the smartmoney fetchers (its 13F ledger keeps only a 2-year window); backfill older 13Fs from EDGAR to lengthen the 13F history |

## 0. Decisions so far

| # | Decision |
|---|---|
| D1 | Runs on the local Mac via launchd; the built site is pushed to GitHub Pages |
| D2 | The main update script runs **daily** and covers market data, Congress, 13F, categories, methods, evaluation and the site |
| D3 | Congress and 13F data come from smartmoney's ledgers first; its fetchers get ported later |
| D4 | Historical S&P 500/400 membership is rebuilt from Wikipedia's change tables |
| D5 | Python package `market`, GitHub repo `zacseidel/options` |
| D6 | Efficiency is a design constraint: each piece of historical data is fetched once, no large raw stores, incremental daily work |
| D7 | Plans: **Stocks Starter** (5-yr rolling history, 15-min delayed, reference, corporate actions, indicators) and **Options Starter** (2-yr history, 15-min delayed, greeks/IV/OI in snapshots, flat files). Probe results: `data/state/probe-2026-10-09.json` |
| D8 | **Stocks are gathered broadly; options only for a select set of underlyings** (watchlists flagged `options: true` + names entering configured category slots, capped at 200) |
| D9 | **Watchlists** (`watchlists.yaml`) are first-class universes alongside S&P 500/400 |
| D10 | **Option set** = option watchlists + names entering `mom12_sp500.top5`, `rankmom_sp500.top5`, `mom12_megacap.top5`, `laggards_mega10.top2` (the categories whose Sharpe beats SPY's); ~99 names over 2 years |
| D11 | **Option legs close when the stock would**: the same session the stock exit fills (report-driven exits). An open short put is bought back then, not left to run |
| D12 | **Assigned puts**: shares are held until the name leaves the slot, then sold with the stock exit |
| D13 | **Diagonal**: long call Δ 0.80 (6m: first expiry ≥ 180d) + short call (~21d, Δ 0.20 / 0.30), short leg re-sold at expiry; everything closes at window end |
| D14 | **Option fills at the traded price** (mid of the day's open and close), no spread haircut: there is no bid/ask history, and the haircut, not the method, decided the LEAP results |
| D15 | **Long calls**: expiry = first ≥ 180d / ≥ 365d with a traded strike within ±0.05 Δ (most-traded); sizing = match stock, 50% or 100% of capital in calls; no qualifying call → hold the stock until one appears |
| D16 | **Tracked option set**: 3 methods per base (Defensive / Balanced / Aggressive) chosen from the grid on 2026-10-09; half-Kelly stays the per-trade 0.5·(p − q/b), shown with position = half-Kelly ÷ stock-equivalent exposure |

---

## 1. The model

```
Universe ─► Category ─► Slot ─► Hold rule ─► Instrument ─► Evaluation
 (who)      (ranked      (which    (when we want   (how we get     (how well)
            list/date)   ranks)    exposure)       exposure)
                 ▲                 └──── Method ────┘
           Sources (funds, members) scored as-of each date
```

| Concept | Definition | Examples |
|---|---|---|
| **Universe** | Point-in-time set of securities | all US common stock, S&P 500, S&P 400, top-N by market cap |
| **Source** | Entity whose disclosures create signals, with an as-of skill score | 13F funds, members of Congress |
| **Category** | Pure function `(as_of, panel, sources) → [security, rank, score, features]` | 12-mo momentum, rank momentum, Munger dip, mega-cap laggards, industry movers, top-fund new buys, Congress out-performer buys, convergence |
| **Slot** | Which ranks to take | top 5 · ranks 6–10 · all signals · top 2 |
| **Hold rule** | Turns category output into **exposure windows** (security, start, end) | while listed · leave-next-session · until close < EMA21 · until close > SMA10 · fixed 21 sessions (stacked lots) |
| **Instrument** | Turns each exposure window into trades and legs | long stock · cash-secured put · covered call · LEAP call |
| **Method** | Hold rule + Instrument | "while listed, via 30–45 DTE 0.25Δ puts" |
| **Strategy** | Category × Slot × Method | `rankmom500 · top5 · leave-next · CSP(30-45, .25Δ, 50% take)` |

**Why split hold rule from instrument:** a strategy's exposure windows are computed once and
reused by every instrument. Adding CSP / CC / LEAP to an existing strategy then needs no new
signal work, just the option legs for windows that already exist.

---

## 2. Point-in-time and fill rules (enforced by tests)

1. Every input row carries `available_at`. A category at `as_of` sees only rows with
   `available_at ≤ as_of`. Daily bars become available after the close. Disclosures become
   available at their filing or disclosure time.
2. Source skill is recomputed **as of** each date from earlier filings only, which removes
   smartmoney's look-ahead.
3. **Stock fills:** a signal known after the close of day D fills on the next session at VWAP,
   falling back to mid(open, close). Technical exits are decided on a completed close and filled
   the next session.
4. **Option fills:** the next session's traded price, mid(open, close) from the option day bar, with
   no spread haircut (D14). There are no historical quotes on 15-min-delayed plans. The haircut
   machinery (h = max(3 %, $0.05 / mid), widened past 180 DTE or |Δ| < 0.15) remains for sensitivity
   runs; live snapshots can record bid/ask so a cost can be calibrated later.
5. **Total return:** store unadjusted bars plus splits and dividends, adjust on read with a small
   cumulative-factor table, and credit dividends on stock legs.
6. Securities are keyed by `security_id` (FIGI-based), with `ticker_history` mapping tickers to
   dates. This handles reused and renamed tickers.

---

## 3. Data sources & call budget

Polygon (Massive) facts used in this design:
- **Stocks:** grouped daily returns every US stock's OHLCV + VWAP in **one call per session**.
- **Options flat files:** one CSV.gz per session covering the whole US options market (ticker,
  OHLC, volume, transactions; no VWAP, no OI), about 1.5–3 MB per day, published around 11:00 ET
  the next day. History is **2 yr on Starter, 4 yr on Developer, 5+ yr on Advanced**. Historical
  quotes are Advanced-only.
- **Option snapshot by underlying:** today's chain, 15-min delayed. Measured coverage: OI on 100 % of
  contracts, greeks/IV on ~60 % (the illiquid ones are missing), **no bid/ask** on Starter. Filters such as
  `strike_price.gte/lte` and `expiration_date.gte/lte` keep it to one page per underlying.
- Stock history is a **rolling** 5-year window; because we store what we fetch, our own history keeps
  growing past 5 years.
- An option ticker can be computed from its terms (`O:AAPL261120P00150000`), so contract lists
  are needed only for discovery.

### 3a. One-time backfill
| Data | Method | Calls / downloads | Kept |
|---|---|---|---|
| Stock bars, 5 yr | grouped daily, `adjusted=false` | ~1,260 calls | all common stock + benchmark ETFs |
| Splits, dividends | reference endpoints, paginated | ~50 calls | all |
| Ticker events and details | only securities that were ever in a tracked universe | ~2,000 calls | compact `securities`, `ticker_history`, `company_meta` |
| Shares outstanding history (for point-in-time market cap) | SEC company-facts, one call per company with full history | ~1,200 | quarterly rows |
| S&P 500/400 membership history | Wikipedia lists + change tables | 2 pages | membership intervals |
| Options history | flat files, one per session (~2.5–4 MB), **streamed and filtered to the select option set, never stored raw** | ~500 files, ~1.7 GB transferred once | option panel (§4) |
| Congress, 13F | smartmoney ledgers, local file read | 0 | normalized tables |

### 3b. Daily run
| Data | Calls |
|---|---|
| Grouped daily for any session not yet stored (fills gaps on its own) | 1 |
| Splits and dividends since the last checkpoint | 2 |
| New tickers or ticker events (only for securities not seen before) | 0–10 |
| SSGA SPY + MDY holdings | 2 downloads |
| Wikipedia S&P lists (weekly, or whenever SSGA shows a change) | 0–2 |
| Previous session's options flat file, streamed and filtered | 1 download |
| Option snapshots, **one per underlying** with open option legs, new entries today, or live candidates | ~50–200 |
| News, only for tickers new to a report, cached 14 days | ~0–40 |
| T-bill rate (FRED DTB3) for Black-Scholes and cash yield | 1 |
| Congress: smartmoney's incremental House/Senate fetch, then ledger import if it changed | a few, polite |
| 13F: EDGAR daily form index; pull filings only for new 13F-HR from candidate funds | 1 + new filings |
| **Total** | **~60–260 calls/day**, nearly all for option snapshots |

**No-refetch rule:** a `fetch_log(source, key, coverage, fetched_at)` table records what has been
fetched. Closed sessions, expired contracts and completed filings are immutable and are never
requested again. Snapshot calls are de-duplicated per underlying per run.

---

## 4. Storage

**One DuckDB file**, `data/market.duckdb`, plus a small `data/state/` directory. Nothing goes in
git. There is no raw-response archive: flat files and API payloads are parsed in a stream and
discarded.

| Table | What | Est. size |
|---|---|---|
| `bars_daily` | unadjusted OHLCV + VWAP, all common stock, 5 yr (~7 M rows) | ~120 MB |
| `splits`, `dividends`, `adj_factors` | corporate actions + cumulative factors | <5 MB |
| `securities`, `ticker_history`, `company_meta`, `shares_history` | reference | <10 MB |
| `calendar` | sessions, early closes (from grouped daily + Polygon holidays) | tiny |
| `universe_membership`, `universe_weights` | intervals; SSGA weights only on change days | <5 MB |
| `option_bars` | **option panel**: select option set × bands below | ~0.35 MB per underlying per 2 yr → ~35–70 MB for 100–200 names |
| `option_marks` | daily snapshot marks for contracts we hold or show (bid/ask/IV/Δ/OI) | <5 MB |
| `congress_trades`, `f13_filings`, `f13_holdings`, `entities`, `entity_scores` | sources | ~20 MB |
| `category_snapshots` | top-K per category per date (K = max(slot) + 15, e.g. 25), not the whole universe | ~20 MB |
| `events` | disclosures, 13F changes, universe adds/drops, trade opens/closes | <5 MB |
| `windows`, `trades`, `legs`, `nav_daily`, `metrics` | evaluation outputs | ~20 MB |
| `runs`, `fetch_log`, `versions` | operations | tiny |
| **Total** | | **~300 MB** |

**Option panel filter** (measured on 5 real sessions, 2026-10-02 → 10-08). A row from the daily
options file is kept only if its underlying is in the **select option set** (D8) and it falls in a band:
short-dated (7–60 DTE) puts at 70–102 % of spot or calls at 98–120 %, or LEAP calls (180–800 DTE) at
50–100 %, with volume ≥ 5. The stored columns are `session, root, expiry, kind, strike, open, close,
volume, transactions`; the OCC ticker string, high and low aren't stored. Cost: **~35 rows and ~0.5 KB per
underlying per day**. For comparison, the full S&P 900 would cost ~210 MB with these bands, or ~630 MB
with draft 2's wider bands. Two follow-ups:
- A held contract that drifts outside the bands (say, a put after a crash) is fetched per contract by
  REST and cached in the same table.
- Names added to the option set later are backfilled in **one batched re-stream** of the 2-yr files for
  all pending additions (~500 downloads, run only when the set has grown), so files are never re-read
  one name at a time.

**Site output:** a few MB of JSON, regenerated each run and force-pushed as a single commit to
`gh-pages`, so there's no history. Only the files that changed are rewritten.

---

## 5. Universes

| Universe | Point-in-time source |
|---|---|
| `us_common` | `securities` where type = CS and the security traded that session; survivorship-free |
| `sp500`, `sp400` | Wikipedia change tables replayed backward from today's SSGA list, then matched to `security_id` through `ticker_history` (handles BRK.B / BRK-B and renames). The S&P 400 page's change history is thinner, so a coverage report is built and gaps are flagged in the UI. |
| `megacap25`, `top50` | point-in-time market cap = adjusted close × shares outstanding (SEC facts), ranked within `sp500`; GOOG/GOOGL combined. SSGA weights are used for live dates. |
| `sp400_large15` | top 15 % of `sp400` by market cap (replaces MDY weight historically) |
| `watchlist:<name>`, `watchlists` | `watchlists.yaml`: plain tickers or `TICKER: added-date`. Removing a name closes its membership on the sync date, so history is kept. Undated names count for all history, and backtests on them are flagged as hindsight-selected. |
| `options` (the select option set) | watchlists with `options: true` ∪ names entering `options.underlyings.category_slots`, from the date they enter; capped by `max_underlyings` |

---

## 6. Categories (initial registry)

Each category is a module with `@category(id, group, universe, version)` and
`compute(ctx) → DataFrame`. All categories in a run share **one in-memory adjusted price panel**,
loaded once per run. The old repos re-queried prices separately for each cohort.

| Group | Category | Rule (from the existing repos) |
|---|---|---|
| Momentum | `mom12_{megacap,sp500,sp400}` | 12-mo return rank, rank ≤ rank one month ago |
| Momentum | `rankmom_{sp500,sp400}` | best average of 3/6/12-mo ranks |
| Momentum | `stall_flag` (overlay) | no new 60-session high for >15 sessions; isolated vs broad |
| Reversion | `laggards_mega10` | worst average 3/6/12-mo rank of the 10 largest |
| Reversion | `munger_top50`, `munger400l`, `munger400r` | close < SMA200 in the last 10 sessions and close > SMA10 |
| Industry | `industry_up`, `industry_down`, `industry_groups` | SIC-2 cap-weighted 12-mo return; largest stock rank changes |
| Smart money | `fund_new_buys` | Σ max(alpha,0) × hit-rate × position/book over top as-of funds |
| Smart money | `fund_curated_{watchlist,healthcare}` | holdings of pinned funds |
| Smart money | `congress_outperformer_buys` | purchases by as-of top-quartile members in the last N days |
| Smart money | `congress_regulated_bets` | cap × committee × consensus composite |
| Smart money | `convergence` | new buys by both top funds and top members |

Event-driven categories, the smart-money ones, are evaluated as of their **disclosure** dates.

---

## 7. Methods

### 7a. Hold rules (exposure windows)
| Rule | Params | Behaviour |
|---|---|---|
| `while_listed` | — | open on the first listing while flat; close at the first report without it |
| `leave_next_session` | — | as above, but sell the session after the dropping report; relisting before then cancels the sale |
| `price_exit` | indicator (EMA21, SMA10), direction | exit the session after a qualifying close |
| `fixed_hold` | N sessions, `stack` | each listing opens its own lot |
| `rebalance_on` | report days | ▸ DEFAULT Tue/Fri, the same cadence as the current live record; daily is available as a variant |

### 7b. Instruments
Built 2026-10-09 (`methods/instruments/options.py`, evaluated by `evaluate/options_engine.py`). Every
option method reuses its base stock strategy's windows; every leg closes the session the stock exits (D11).

| Instrument | Entry inside a window | Management | Window ends | Capital & return basis |
|---|---|---|---|---|
| `stock` | buy at window start | dividends credited | sell | cost |
| `csp` | sell put at the target Δ; any expiry 14–21 DTE (momentum) or 30–45 (laggards) | OTM expiry → sell the next put the next session; ITM → assigned, shares held to window end, no more puts (D12) | buy back the put; sell any shares | collateral = strike × shares; cash earns 4 % |
| `covered_call` | buy shares + sell call at the target Δ, expiry nearest 21 DTE (14–28) | OTM expiry → sell the next call; called away → re-buy shares and sell a call the next session | buy back the call, sell shares | stock cost |
| `leap` | buy call at the target Δ (±0.05, most-traded strike), first expiry ≥ 180 / ≥ 365 DTE (D15) | roll at the window's value below 120 / 180 DTE; no qualifying call → hold the stock, swap in when one appears | sell the call | `sizing`: delta (moves like the stock), 0.5 / 1.0 of capital in calls; rest in T-bills |
| `diagonal` | 6m Δ 0.80 call sized to match the stock + ~21d short call on the same shares (D13) | short re-sold each expiry; ITM short settled at intrinsic | close both | as LEAP |

Method choice comes from the grid (`python -m market.evaluate.option_grid` → `docs/options_grid.md`):
25 methods × 4 bases over the options history. Findings (2026-10-09): 12m Δ0.60 calls add the most
return at a Sharpe at or above the stock's; Δ−0.20 puts are the low-risk way in; covered calls never
beat the stock because momentum's profit is the right tail a call sells; 6m all-in calls have the
biggest numbers and the worst Sharpe (drops of 69–80%).

**Contract selection.** On the session before the fill (the report's as-of close), read candidates from
`option_bars` (the traded contracts in band). Compute IV and Δ with Black-Scholes using the T-bill rate and dividend yield.
Short legs: the contract closest to the target Δ with volume ≥ ▸ 10 and transactions ≥ ▸ 3 (nearest
21 DTE for calls). Long calls: volume ≥ 2, Δ within ±0.05 of target, the most-traded such strike in the
first qualifying expiry. If none qualifies, skip the leg and record why. Live entries use the snapshot's own greeks.

**Assignment model.** Puts and calls are settled at expiry against the underlying's close. Early
assignment is modelled only for covered calls deep in the money just before an ex-dividend date
(extrinsic value < dividend).

**Options history limit.** Option methods can only be backtested over the options-plan window: 2
years on Starter, 4 on Developer. Earlier periods show stock-only results, and the UI marks where
options history begins.

### 7c. Live method view ("what would each method do today")
For current members of each displayed category slot, the evening run reads one snapshot per
underlying. It shows the contract each instrument would choose: premium, annualized yield on
collateral, breakeven, Δ, IV, OI and bid/ask. These rows are kept in `option_marks` only for
contracts that are opened or displayed.

---

## 8. Evaluation

- Engine pipeline: `windows(strategy) → trades/legs(instrument) → nav_daily → metrics`.
- **Incremental:** the daily run advances live windows, trades and NAV by one session. Full
  backtests rerun only for strategies whose `version` hash changed (category code or params, hold
  rule, instrument params, haircut), and only that strategy's downstream rows are rebuilt.
- **Modes:** `backtest`, computed from history and rebuildable, and `live`, the as-published record
  that is never rewritten. Legacy momentum picks and eval trades since Jan 2026 are imported as
  `live` to continue the record.
- **Metrics:**
  - returns: 12M, 3M, since inception, and CAGR, all vs SPY
  - Sharpe (log returns, T-bill rate), Sortino, max drawdown, time underwater
  - trade stats: win %, payoff ratio, half-Kelly (≥ 20 closed trades), independent-run count for stacked lots
  - options: return on capital, annualized yield, assignment rate, capture vs the same windows in stock, haircut sensitivity (0×/1×/2×)
- **Portfolio policy:** equal weight per open window, rebalanced on event days (as in eval). For
  options instruments, equal *capital* per window.
- **Validators** (ported from eval) run on every build: unique ids, every trade traces to a
  signal, no weekend or future dates, exit after entry, technical exits actually triggered, no
  overlapping windows except stacked lots, and option legs that expire on real expiry dates.

**Strategy grid** (`strategies.yaml`). Explicit lists plus small grids, for example
`categories: [mom12_sp500, rankmom_sp500] × slots: [top5, next5] × methods: [stock, csp_std, leap_std]`.
Each strategy has `visible: true|false`. Hidden variants keep being evaluated.

---

## 9. Reports & change tracking

- A **report** is the `live` category snapshots for a date. No HTML or charts are stored per date.
- **Diffs are derived when needed** for any two dates: adds, drops, rank moves, score changes, and
  the events in between (new Congress trades, 13F new, increased, decreased or exited positions,
  universe changes, strategy trades opened or closed, assignments).
- Published snapshots are immutable. Backtest snapshots carry a category `version`.
- Every source sits on one timeline: momentum report days, Congress disclosure batches, and 13F
  waves (diff = quarter over quarter, for each fund and across all funds).
- ▸ DEFAULT: categories are computed and stored daily, reports are *published* Tue/Fri, and the UI
  can compare any two stored dates.

---

## 10. Site & navigation

A static single-page app (vanilla JS + Chart.js, no build step) with hash routes. Each route loads
one small JSON file.

```
Today       #/                     changes since last report · new disclosures · pending exits & expiring legs ·
                                   strategy leaders · market strip
Reports     #/reports              timeline (momentum, Congress batches, 13F waves)
            #/report/D             every category on D, ▲▼ new/dropped vs the previous report
            #/compare/D1/D2        diff any two dates
Categories  #/categories           groups: Momentum · Reversion · Industry · Smart money · Convergence
            #/category/ID          current list + live method view · membership timeline · strategies using it
Strategies  #/strategies           matrix: category×slot rows × instrument columns, cell = chosen metric;
                                   filters: universe, hold rule, live|backtest, hidden variants, haircut
            #/strategy/ID          NAV vs SPY & vs same-signal stock, rolling 3M, drawdown, metrics, trades/legs, rules
Stocks      #/stock/T              chart + MA dots · category history · fund holders & changes · Congress trades ·
                                   option candidates (live) · news · financials
Sources     #/funds  #/fund/CIK    as-of leaderboard · holdings by quarter with changes
            #/members #/member/ID  leaderboard · trades · committees
Portfolio   #/portfolio            personal positions graded with the same metrics
About       #/methodology          rules, fills, haircut, data coverage (options history start, S&P 400 gaps)
```

Every ticker, category, strategy, fund and member is a link.

**Export:** `index.json`, `reports/D.json`, `categories/ID.json`, `strategies/ID.json`,
`stocks/T.json` (only tickers that have been in a category in the last 2 years; 1-yr compact bars),
`funds/CIK.json` (top-N and pinned only), `members/ID.json`.

---

## 11. Code layout & daily run

```
pyproject.toml   config.yaml   strategies.yaml
src/market/
  data/        polygon.py (async, retries, no throttle) · flatfiles.py (S3 stream + filter) · calendar.py
               securities.py · bars.py · corpactions.py · universe_ssga.py · universe_wiki.py
               shares_sec.py · options.py (panel, snapshot, BS greeks) · rates.py · ledgers_smartmoney.py
  store/       schema.sql · db.py · panel.py · fetch_log.py
  categories/  registry.py · momentum.py · rankmom.py · laggards.py · munger.py · industry.py
               funds.py · congress.py · convergence.py
  sources/     fund_scores.py · member_scores.py
  methods/     hold_rules.py · instruments/{stock,csp,covered_call,leap}.py · select_contract.py · fills.py
  evaluate/    engine.py · portfolio.py · metrics.py · validate.py · versions.py
  reports/     snapshot.py · diff.py · export.py
  ops/         run.py · probe.py · publish.py
site/          index.html · js/ · css/
ops/launchd/   com.zacseidel.market.daily.plist · run.sh
tests/
```

**Daily run** (`run.py`, every step idempotent and incremental):
1. Preflight: API key, push credentials, disk space, DB lock.
2. Calendar: list sessions not yet stored. If there are none, run only steps 5, 9 and 10.
3. Market data: grouped daily for missing sessions → corporate actions → adjustment factors.
4. Options: stream any options flat files not yet loaded (previous session) into `option_bars`.
5. Reference & sources: SSGA → membership changes (→ Wikipedia refresh if changed); new-ticker
   details; Congress incremental fetch + ledger import; EDGAR daily index → new 13F filings →
   update entity scores for affected entities only.
6. Categories: load the panel once and compute today's snapshots.
7. Methods: advance live windows; collect the underlyings that need snapshots (open legs, entries,
   live view); one snapshot each; open, roll or close legs.
8. Evaluation: append NAV and metrics. Rebuild any strategies whose versions changed (can be
   skipped with `--no-rebuild`).
9. Reports: on publish days, freeze today's snapshot as the report.
10. Export the changed JSON → force-push `gh-pages` → write the `runs` row → macOS notification on
    failure.

**Schedule** (launchd, weekdays): 17:30 MT, catch-ups at 20:30 MT and 07:00 MT the next day.
`run.sh` skips on battery, keeps a per-session success stamp, logs to `~/Library/Logs/market/`
(90-day retention), and supports `--force`, `--dry-run`, `--as-of D` and `--only step`. Weekends:
one Saturday run for disclosures only.

---

## 12. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0 Setup & probe** | repo, pyproject, config; `probe.py` checks entitlements (stock history depth, grouped VWAP, options flat-file access and depth, snapshot greeks, bid/ask in snapshot) and **measures the option-panel size** for 1 month | plan tiers and storage numbers confirmed |
| **1 Data foundation** | calendar, securities, 5-yr bars, corporate actions, SSGA + Wikipedia membership, SEC shares, smartmoney ledger import | point-in-time panel tests; adjusted closes match Polygon `adjusted=true` on spot checks; membership coverage report |
| **2 Categories** | momentum, reversion and industry categories as pure functions; snapshots; legacy import | **parity** with momentum's `top10_*` tables on shared dates |
| **3 Evaluation: stock** | hold rules, stock instrument, engine, NAV, metrics, validators, versioned incremental rebuilds | **parity** with eval's `positions.json` and NAV for 2026; 5-yr stock backtests |
| **4 Options** | option panel backfill, BS greeks, contract selection, CSP / CC / LEAP instruments, live method view | hand-checked sample trades; haircut sensitivity reported |
| **5 Reports, site, ops** | snapshots→reports→diffs, full navigation, export, gh-pages, launchd | runs unattended for 2 weeks alongside the old sites, then momentum + eval Actions are retired |
| **6 Smart money** | as-of fund and member scores; fund, Congress and convergence categories; Sources pages; 13F wave reports | no look-ahead (tested); per-report changes visible |
| **7 Consolidation** | port smartmoney fetchers (incl. OCR) and pages; optional intraday "live" refresh command | smartmoney retired |

---

## 13. Open questions

1. ~~Options plan tier~~ → Options Starter: option backtests cover 2 years (D7).
2. **Which category slots feed the option set?** For example `mom12_sp500.top5` and
   `rankmom_sp500.top5`. Over 2 years each top-5 slot brings in roughly 50–100 names, so a few slots
   plus the watchlists stays well under the 200 cap.
3. **CSP behaviour at window end:** let the put run to expiry (default) or buy it back?
   **Assignment:** hold until window end (default), sell the next session, or wheel?
4. **Report publish days:** Tue/Fri (default) or daily?
5. **Smartmoney during the transition:** keep its weekly launchd job, and have our daily run call
   only its incremental Congress fetch? Or move all its scheduling under our runner now?
