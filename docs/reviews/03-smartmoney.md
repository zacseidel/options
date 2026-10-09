# Review 3 — `zacseidel/smartmoney` (13F hedge funds + Congress trades)

Reviewed 2026-10-08. ~9.7k lines Python (24 modules in `src/`, 12 in `src/hedge/`), Jinja
templates, 5 test files. Repo is 710 MB of history (committed grouped-price caches,
~3.8k rendered pages). Already **runs locally** via launchd and pushes to GitHub Pages;
Actions workflows are manual-only.

Covers two signal sources and a combined "Smart Money" dashboard. (Is there a separate
Congress repo, or is this it? — question for the user.)

## Ingestion (non-Polygon data — the valuable, hard-won part)
| Source | Module | Notes |
|---|---|---|
| House PTRs | `fetch_house.py` | Clerk annual `FD.zip` index → PTR PDFs → `pypdf` text parse |
| House paper PTRs | `ocr_scanned.py`, `ocr_ptr.py` | rotate + grid detect + tesseract + fuzzy ticker match (cutoff 0.86); ~28% of ledger rows are OCR |
| Senate PTRs | `fetch_senate.py` | eFD agreement + DataTables search → HTML |
| Committees | `fetch_committees.py` | unitedstates/congress-legislators → jurisdiction → industries |
| 13F filers | `hedge/discover_filers.py` | EDGAR quarterly `form.idx`, AUM + holdings count from primary_doc |
| 13F holdings | `hedge/fetch_13f.py` | submissions feed → info-table XML, $ vs $-thousands scale detection, aggregate by CUSIP |
| CUSIP→ticker | `hedge/resolve_cusip.py` | OpenFIGI batched (key makes it ~125× faster) + Polygon fallback + overrides |
| Financials | `fetch_financials.py` | EDGAR company-facts annual lines |

Ledger today: 17,621 Congress transactions (disclosures 2024-06-18 → 2026-10-05; median
26 days trade→disclosure, p90 113 days). 9,148 13F filers, 678 funds on the leaderboard.
Local `~/Projects/smartmoney` holds the uncommitted 13F holdings ledger (18 MB) and CUSIP map
— reusable as seed data.

## Mapping onto Universe / Category / Method / Evaluation

### Categories this adds (event-driven, signal date = public disclosure date)
- **Hedge "buying now"**: new 13F positions scored Σ_funds max(alpha,0) × hit-rate ×
  (position / book), indexed 0–100. Only top-N funds by alpha (200) with alpha > 0.
- **Hedge "alpha drivers"**: stocks contributing most to ranked funds' alpha.
- **Curated fund books**: watchlist funds (Thiel Macro, Situational Awareness, Duquesne,
  Thrive, Atreides, Scion, Ratan) and healthcare specialists (Perceptive, Opaleye, …).
- **Congress out-performer buys**: purchases by top-quartile-alpha members disclosed within
  N days, scored Σ position$ / member total$.
- **"Regulated bets"**: cap-bucket multiplier × committee-jurisdiction boost × consensus.
- **Convergence**: names newly bought by both hedge and Congress out-performers.
- Also: SMA10/50/200 + up/down-volume "momentum dots" per ticker (overlaps review 1).

### A new idea: evaluating *sources*, not just strategies
Both halves rank **entities** by "follow the disclosure" performance:
- Fund: mirror the long book from each filing date to the next, value-weighted; chained
  return, alpha = cum return − cum SPY, hit rate (quarters beating SPY), coverage (share of
  book priced), per-stock alpha attribution. Gates: ≥4 filings, ≥90% coverage, hit rate
  > 50%, AUM ≥ $100M, 5–150 holdings, passive managers blocklisted.
- Member: buy at close on/after disclosure, a sale disclosure closes all lots, unsold held
  to today; dollar-weighted by amount-range midpoint; alpha vs SPY; ≥3 positions.
These entity rankings are **inputs to categories** ("what are the best funds buying").

### Evaluation already shared with eval
`generate_decisions.py` (personal position log in `positions.md`) re-implements eval's
NAV builder, Sharpe, trade stats and half-Kelly — evidence these belong in one shared
library.

## Problems to fix in the new design
1. **Look-ahead in entity rankings.** Fund alpha / member out-performance is computed over
   the whole trailing window, then used to pick "what top funds are buying". Fine for a live
   page, but a backtest of that category must rank funds/members using only filings
   available *before* each signal date. (`outperformer_history.json` began point-in-time
   snapshots in June 2026 — the right idea, but needs to be computed historically.)
2. **Inconsistent execution conventions.** Congress uses the *close* on/after disclosure;
   13F uses filing-date closes; eval uses next-session VWAP. Unify on one rule.
3. **2-year window** everywhere (free tier). EDGAR 13F and the House/Senate archives go back
   much further, so 5-year backtests of these categories are feasible, and unlike index
   membership these signals have no survivorship problem.
4. Big monolithic JSON files (`transactions.json` 11 MB, `company_info.json` 5 MB) and
   grouped-price caches committed to git → SQLite tables in the shared store.
5. UTC timestamp conversion (`utcfromtimestamp`) again — same bug class as review 2.
6. Options in 13F books (`put_call`) are skipped; long shares only.

## Keep / reuse
- All ingestion modules above (incl. OCR) — port them, or have the new system consume their
  ledgers as signal sources first and port later.
- Entity backtests (fund mirror, member follow) as point-in-time scoring functions.
- Scoring formulas (skill-weighted conviction, out-performer share, convergence).
- `taxonomy.py` (SIC→industry, cap buckets, committee→industry).
- **Local ops pattern** — reuse directly for the new project:
  - launchd agent with catch-up firings (02:00 / 07:00 / 12:00 / 18:00).
  - `weekly_update.sh`: skip on battery, ISO-week success stamp, logs in
    `~/Library/Logs/<project>/`, 90-day log retention, `--force`.
  - `update.py`: calendar-driven dispatch (detect new 13F wave: quarter end + 45 days,
    10-day grace for late filers), `--dry-run`, and **verify push credentials up front**.
  - Polite, resumable, capped fetches; descriptive User-Agent for SEC/House/Senate.
