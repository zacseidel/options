# Handoff — where things stand (2026-10-09)

Read this first, then `docs/PLAN.md` (Status table at the top) for the full design.

## Run it
```
cd ~/Projects/options
.venv/bin/python -m market.ops.run              # daily pipeline (incremental)
.venv/bin/python -m market.ops.run --full       # + weekly reference refresh, rebuild every category
.venv/bin/python -m market.ops.run --only export
.venv/bin/python -m pytest -q                   # 27 tests
cd site && python -m http.server 8792           # view the site at http://127.0.0.1:8792
```
Python is the conda env at `.venv` (3.12). Secrets in `.env` (never print them).

## Pipeline steps (`src/market/ops/run.py`)
watchlists → universes (weekly) → **disclosures** → bars → **fund_periods** → **signals** →
corpactions → market_caps → **leaders** → categories → evaluation → export

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

## Fixed this session
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
2. Options phase: option panel for the select set, then CSP / covered call / LEAP / diagonal per
   category over 2 years. Open question: which category slots feed `config.options.underlyings.category_slots`.
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
