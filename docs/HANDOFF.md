# Handoff — where things stand (2026-10-09, late)

Read this first, then `docs/PLAN.md` (Status table at the top) for the full design.

## Run it
```
cd ~/Projects/options
.venv/bin/python -m market.ops.run              # daily pipeline (incremental)
.venv/bin/python -m market.ops.run --full       # + weekly reference refresh, rebuild every category
.venv/bin/python -m market.ops.run --only export
.venv/bin/python -m pytest -q                   # 40 tests
cd site && python -m http.server 8792           # view the site at http://127.0.0.1:8792
```
Python is the conda env at `.venv` (3.12). Secrets in `.env` (never print them).

## Pipeline steps (`src/market/ops/run.py`)
watchlists → universes (weekly) → disclosures → bars → fund_periods → signals →
corpactions → market_caps → leaders → categories → **options** → evaluation → export

New this session (bold):
- **disclosures** (`market.smartmoney.ingest`): runs smartmoney's own `fetch_house` / `fetch_senate`
  (its interpreter `/Users/zacseidel/opt/anaconda3/bin/python3`, its repo dir), and scans EDGAR's
  daily form index for 13F-HRs by funds already in the ledger → `fetch_13f.run(those ciks)`.
  Skips if smartmoney's own update is running. Writes smartmoney's ledgers. (~1–12 min)
- **fund_periods** (`market.smartmoney.hedge.sync_periods`): prices each completed 13F holding
  period once (grouped-daily adjusted closes, discarded) → `fund_periods`; position weights and returns for
  funds that ever rank → `fund_period_positions`.
- **signals** (`market.smartmoney.pipeline.signals`): Congress-bought names + top-30 13F signal
  names per report date → universe `signals` → `securities.extend()` → `bars.backfill_new_securities()`
  → `corpactions.sync_new_tickers()` → `bars.repair_gaps()`.
- **leaders**: point-in-time top-50 Congress members / 13F funds per report date → `entity_scores`.

## Categories (18 strategies in `strategies.yaml`)
| Group | Categories | History from |
|---|---|---|
| Momentum | mom12_sp500/sp400/megacap, **rankmom_sp500/sp400** | late 2022 |
| Reversion | laggards_mega10, munger_top50 | late 2022 |
| Congress | **congress_buys** (top-5 members' buys, 120 d), **congress_holdings** | 2025-01 |
| Hedge funds | **hedge_buys** (top-200 funds' new positions), **hedge_drivers** (alpha contributors still held) | 2025-05 |

Definitions are on the site's Methodology page and in the module docstrings
(`src/market/smartmoney/congress.py`, `hedge.py`, `src/market/categories/smartmoney.py`).

## Results (since inception, total return CAGR; SPY ≈ 18–22% over the same windows)
SP500 top5 64.8% · RankMom500 top5 54.8% · Megacap top5 42.4% · SP400 top5 40.3% ·
13F Buys next5 64.6% / top5 38.5% · 13F Drivers next5 63.8% / top5 15.9% · Laggards 35.5% ·
RankMom400 top5 22.6% · Congress Buys 12.3% · Congress Holdings 9.4% · Munger 14.6%.
13F and Congress windows are short (~15 and ~21 months), so treat those numbers as anecdotal.

## Member and fund profiles (2026-10-10)
- `#/member/<id>` and `#/fund/<cik>` for every member / fund that has ranked top 25 on any report date
  (`export_profiles.py`; 59 members, 162 funds). Rebuilt by every export, so they stay current and the
  set only grows. Each shows 1y / 2y (ranking) / since-data-start records, dollars disclosed (Congress:
  purchase and sale range midpoints; 13F: reported book), rank-history chart, copied lots or quarterly
  books, holdings. Leaderboards gained a Bought (2y) / 13F book column and links.
- Scoring is unchanged and matches smartmoney: Congress alpha = dollar-weighted average of per-purchase
  (return − SPY) over purchases disclosed in the trailing 730 days, not annualized, ≥5 purchases;
  funds = compounded follow-the-filing quarters that started in the trailing 730 days.
- **Why the top alpha moved:** the Congress ledger starts 2024-06-18, so "2 years" was really "since
  June 2024" until mid-2026; since then 2024 purchases have been dropping out (e.g. Wasserman Schultz
  81% → 34%, Sessions / McGarvey fell below 5 purchases). Top ranks are also dominated by tiny books
  (Evans: 6 buys, ~$48k). Open question for the user: rank on 1y vs 2y; a minimum-dollars gate.

## New categories (2026-10-10, not in Options)
- **S&P 500 Leaders, Isolated Stall** (`mom12stall_sp500`): momentum10's report-only stall flag made a rule.
  Stalled = highest close of the last 60 sessions is >15 sessions old. If ≤3 of the unfiltered top 10 by
  12-month return are stalled (isolated), stalled leaders are dropped from the Leaders list; otherwise
  (broad) the list is unchanged. Changes the top 5 on 26% of reports.
- **Reasonable Growth Leaders** S&P 500 / 400 (`rgrowth_sp500`, `rgrowth_sp400`): top 12-month return
  with 14-day Wilder RSI strictly between 20 and 80; no rank-improvement filter.

Since 2022-11-29 (CAGR / Sharpe / worst; 3y CAGR):
| Strategy | top 5 | next 5 |
|---|---|---|
| S&P 500 Leaders | 64.8% / 1.04 / −44% (3y 88.6%) | 26.7% / 0.58 / −36% |
| … Isolated Stall | 68.2% / 1.09 / −44% (3y 91.7%) | 26.6% / 0.60 / −37% |
| S&P 500 Reasonable Growth | 66.6% / 1.05 / −40% (3y 91.6%) | 26.2% / 0.53 / −39% |
| S&P 400 Leaders | 40.3% / 0.73 / −46% | 11.1% / 0.21 / −35% |
| S&P 400 Reasonable Growth | 39.5% / 0.72 / −40% | 9.7% / 0.14 / −43% |

## Options (built 2026-10-09)
- **Data** (`market.data.option_panel`): OPRA day-aggregate flat files streamed and filtered to names
  around the windows held by `config.options.underlyings.category_slots` (S&P 500 Leaders, S&P 500
  Rank Momentum, Megacap Leaders top 5; Megacap Laggards top 2) + option watchlists. Coverage per
  (session, root) in `option_coverage`; new names cost a batched re-stream of only their sessions.
  Backfill: 502 files, 1.7 GB streamed in 10 min, 6.1M rows kept.
- **Methods** (`methods/instruments/options.py`): CSP, covered call, long call ("LEAP"), diagonal.
  Long calls take the first expiry ≥180d ("6m") or ≥365d ("12m") with a traded strike within ±0.05 Δ
  (most-traded wins), sized `delta` (moves like the stock), or 0.5 / 1.0 = share of capital in calls;
  rolled at the window's value; if no call qualifies the window holds the stock until one does.
- **Fills at the traded price** (mid of open/close; no haircut) — the user's call: no bid/ask data, and
  the old 3%/6% haircut on ~50 round trips a year was what made LEAPs lose.
- **Grid** (`python -m market.evaluate.option_grid`, ~2.5 min, read-only; writes `docs/options_grid.md`
  + `data/options_grid.json`): 25 methods × 4 bases. Re-run periodically to revisit the tracked set.
- **Tracked set** (`strategies.yaml` → `option_methods.bases`): 3 per base, tier Defensive / Balanced /
  Aggressive, chosen 2026-10-09 from the grid. Retired methods' rows are pruned on a full evaluate.

| Base (stock CAGR / Sharpe / worst) | Defensive | Balanced | Aggressive |
|---|---|---|---|
| S&P 500 Leaders (101% / 1.23 / −44%) | CSP Δ−0.20: 34% / 1.34 / −20% | LEAP 12m Δ0.60, 50% in calls: 166% / 1.49 / −46% | LEAP 12m Δ0.60, 100%: 365% / 1.54 / −57% |
| S&P 500 Rank Mom (82% / 1.14 / −39%) | CSP Δ−0.20: 30% / 1.80 / −10% | Diagonal 6m 0.80/0.30: 74% / 1.51 / −28% | LEAP 12m Δ0.60, 50%: 126% / 1.34 / −42% |
| Megacap Leaders (43% / 0.82 / −36%) | CSP Δ−0.30: 28% / 0.97 / −23% | LEAP 12m Δ0.80, 50%: 56% / 0.92 / −36% | LEAP 12m Δ0.80, 100%: 99% / 0.83 / −56% |
| Megacap Laggards (51% / 1.51 / −19%) | Diagonal 6m 0.80/0.20: 38% / 1.54 / −14% | LEAP 6m Δ0.80, 50%: 103% / 1.45 / −34% | LEAP 12m Δ0.80, 100%: 166% / 1.33 / −48% |

- **Sizing stats**: half-Kelly is the site's per-trade 0.5·(p − q/b) (user's choice); it ignores leverage,
  so option methods also show `stock_equiv` (stock-equivalent exposure at entry) and
  `position` = half-Kelly ÷ stock_equiv (cap 100%).
- **Site**: `#/options` — summary grid (highlight = Sharpe ≥ stock + 0.05), patterns text (hard-coded
  in `app.js` `OPTION_PATTERNS`, from the 2026-10-09 grid run — update when the grid is re-run),
  per-base tables, chart, "if opened today" with DTE and exposure.
- **Caveats**: 2 years; no spread cost; for 24–28% of S&P 500 holdings no 12m call qualified (held stock).
  CSPs still use 14–21d (momentum) / 30–45d (laggards), not the ~21d of covered calls.

## Fixed earlier this session
- `.gitignore` `data/` was hiding `src/market/data/` → now `/data/`; package committed.
- Ticker-history gaps (Polygon events incomplete): Honeywell pre-2026 `HON`, Fiserv 2023–25 `FI`.
  New rules in `securities.ticker_history_rows` + `bars.repair_gaps()` (35 gaps filled).
  Momentum results unchanged.

## Site
Nav: Overview · Reports · Strategies · Categories · **Congress** · **Hedge funds** · Stocks · Methodology.
Congress / Hedge pages: pick a report date → that date's category cards (with diffs),
disclosures/filings since the previous report, leaderboard at that date. Report pages grouped by
section with digest cards. Data: `site/data/congress.json`, `hedge.json` (export_smartmoney.py).

## Open items / next steps
1. **Not yet done** (needs your OK): install launchd agent (`ops/launchd/`), create GitHub repo
   `zacseidel/options` and publish the site (public vs private?).
2. Options: re-run the grid periodically and revisit the tracked set; consider aligning CSPs to ~21d;
   the 13F/Congress categories have no option data yet.
3. 13F history is short (smartmoney ledger starts with Aug-2024 filings and keeps a sliding
   2-year window). Port the 13F fetcher and backfill older quarters from EDGAR to lengthen it and to
   stop old filings being trimmed (stored snapshots survive, but a category rebuild would lose them).
4. Choices made without asking (easy to change, constants at the top of each module):
   Congress min 5 lots to rank, 120-day buy window, ranking starts 2025-01; 13F: min 3 completed
   quarters, ≥25 ranked funds before emitting, amendments ignored, alpha-driver growth chained over the
   fund's stored history.
5. Runtime: the daily run was ~30 s before; with disclosures + smart money expect a few minutes
   (today's runs were slow because the Mac was throttled — battery at 4%, not charging on AC).
6. SSGA holdings as the S&P 400 current-member authority (FORM case).
