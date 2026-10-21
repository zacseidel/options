# Plan — new signal families (draft 1 · 2026-10-21)

Builds on `docs/PLAN.md`. Each `▸ DEFAULT` is a choice you can change. Open questions are in §12.

**Ground rule (S1): nothing existing changes.** Every idea here adds *new* categories, option methods
and strategies next to the current ones. The current 22 stock strategies, 12 tracked option methods, their
rules and their records stay exactly as they are. New strategies enter a **Lab** stage, run and are scored
with the same evaluation, and are promoted, edited or retired over time (§2).

---

## 1. What the plans actually include (probed 2026-10-21)

| Data | Source | Access | History | Notes |
|---|---|---|---|---|
| Financial statements | Polygon `/stocks/financials/v1/*` | **403 — not in Starter** | — | legacy `/vX/reference/financials` is deprecated (410) |
| Financial statements | **EDGAR XBRL `companyfacts`** (free) | ✓ | 2009 → | every fact carries `filed`, `form`, `accn`, `fy/fp`; ~270 KB gz per company |
| Earnings dates | Benzinga earnings via Polygon | **403** | — | |
| Earnings dates | **EDGAR `submissions`**: 8-K item 2.02 + `acceptanceDateTime` | ✓ | full | tells after-close vs pre-open |
| Insider trades | EDGAR Form 4 (daily index + XML); SEC quarterly Form 3/4/5 data sets for backfill | ✓ | 2006 → | ▸ verify the bulk data-set format before building |
| Short interest | Polygon `/stocks/v1/short-interest` | ✓ | 2017 → | twice monthly by settlement date; published ~8 business days later |
| Short volume | Polygon `/stocks/v1/short-volume` | ✓ | 2024-02 → | daily, by venue |
| News + sentiment | Polygon `/v2/reference/news` (`insights`: per-ticker sentiment + reasoning) | ✓ | 2017 → | |
| Free float | Polygon `/stocks/vX/float` | ✓ | current | |
| IPOs, ticker events | Polygon | ✓ | | ticker events already used for renames |
| Splits, dividends | Polygon | ✓ (already ingested) | 5 y | |
| Options day aggregates | OPRA flat files (already streamed daily) | ✓ | 2 y | **95% of each file is discarded today** |

So fundamentals come from EDGAR, which is better for backtests anyway: each number is dated by when it was
filed, not when the quarter ended (point-in-time rule §2.1 of PLAN.md).

---

## 2. Framework additions (Phase 0, needed by everything else) — built 2026-10-21

1. **Strategy stage** — `stage: lab | tracked | retired` in `strategies.yaml` (existing entries default to
   `tracked`), plus `added: <date>`. The site gets a **Lab** page; Lab strategies stay off the main lists,
   like the Options page does today.
2. **Two records per Lab strategy**: the backtest (full history, rules frozen at `added`) and the
   **since-added** record (only reports after `added`; metrics window `since_added`). Thresholds chosen by
   looking at history only prove themselves in the second one. Built as a slice of the backtest, so a
   rule change must come with a new `added` date or id. Later: the `live` snapshot origin (in the schema,
   unused) to freeze reports as published.
3. **Promotion review** ▸ DEFAULT, revisited each quarter: promote after ≥ 6 months since added if Sharpe ≥
   SPY's + 0.10 over both records and worst drop ≤ the parent group's; retire after 12 months if not.
   You decide; the site shows a review table.
4. **Context gains lazy sources** (like `signals` today): `fundamentals`, `events` (earnings, insider,
   corporate actions), `option_flow`, `short_interest`. Categories stay pure functions of the context; each
   source only exposes rows with `available_at ≤ as_of`.
5. **Research modules** — `market.research.<topic>` (read-only, like `option_grid`): event studies that
   write `docs/research/NN-<topic>.md` + JSON. They choose thresholds **on the first part of the history and
   report the rest separately** (▸ DEFAULT: options 12 m / 12 m; fundamentals and events 3 y / 2 y).
6. **Lead-time diagnostic** (new metric, all categories): how often and how many sessions before a name
   first enters S&P 500 / 400 Leaders top 10. Answers "does this find future winners earlier?"
   Baseline (`docs/research/00-lead-time.md`): Fast Rank Momentum entries later join the Leaders top 10
   35–37% of the time, a median 95–117 days early; Megacap Laggards 19% (145 d); Munger Dip 9%.
7. **New instrument `short`** (§10).

---

## 3. Options flow and implied volatility (Phase 1)

**Data.** While streaming each day's file (no extra downloads), keep one row per underlying for the whole
S&P 900 + signals universe in `option_flow_daily` (~1,750 × 500 sessions ≈ 0.9 M rows, ~20 MB):
call / put volume and transactions (all, short-dated OTM), contracts traded, ATM IV at ~30 d and ~180 d
(Black-Scholes from closes, interpolated), 25-Δ put–call skew, term slope. Backfill = one re-stream of
~500 files (~1.7 GB, ~10 min).

**Exploration** (`research/01-option-flow.md`): forward 5 / 21 / 63-session returns vs SPY by decile and by
threshold, for: call volume ÷ 20-day mean; put/call volume ratio and its change; OTM short-dated call share;
IV ÷ 20-day realized vol; skew level and change; term slope. First year picks, second year checks.

**Categories** (only the features that survive): e.g. `optflow_calls_sp900` (unusual call buying),
`optflow_skew_sp900` (puts getting cheaper vs calls), plus bearish mirrors for §10.
Hold ▸ DEFAULT `fixed_hold` 21 sessions, stacked, plus a `while_listed` variant.

## 4. Implied-volatility method choice (Phase 5, after Phase 1)

Add a fourth tier, **Adaptive**, to each option base (the three current tiers don't change). On each
window entry it picks the method from that day's IV state: IV high vs its own history or vs realized vol →
the base's CSP; IV low → its LEAP; in between → the diagonal or stock. ▸ DEFAULT signal: IV ÷ 20-day
realized vol (no 1-year look-back needed, so the whole 2-year history is testable). Evaluated in the option
grid first, then tracked.

---

## 5. Fundamentals (Phase 2) — the biggest enabler

**Data.** `companyfacts` once per company (~1,750 CIKs, ~0.5 GB streamed, parsed and discarded); daily, re-fetch
only companies with a new 10-Q / 10-K / 8-K in EDGAR's daily form index (already scanned for 13Fs).
`fundamentals` table: `cik, concept, period_start, period_end, fp, form, accn, filed, value` for ~30
concepts (revenue tag aliases, gross profit, operating income, net income, diluted EPS, operating cash
flow, capex, buybacks, dividends paid, shares outstanding and diluted weighted shares, debt, equity, cash).
~40 MB. Derived on read: quarterly values (YTD cash flows differenced, Q4 = FY − 9 M), TTM, YoY growth,
**acceleration** (growth now vs one quarter ago), margins and their change, FCF, share-count change,
**multiples** (P/S, P/E, EV/FCF from our point-in-time market caps) and their change.

**New categories** (S&P 500 and S&P 400 each unless noted; none require current momentum):

| Id | Rule (▸ DEFAULT, research-tuned) | What it tests |
|---|---|---|
| `faccel` | revenue and EPS growth both accelerating, margin not falling; rank by composite | expansion → future price |
| `rerating` | earnings growing **and** P/E or P/S expanding vs a year ago | your "multiple expanding" idea |
| `shrinkers` | share count down ≥ 3% YoY, FCF positive | buybacks |
| `compounders` | revenue up YoY in ≥ 10 of the last 12 quarters, low growth variance, FCF positive, shares flat or down; ranked by consistency, then smoothness of the 3-year price path | steady names that never reach the top 5 |
| `emerging` | `faccel` names whose 12-month price rank is improving but still outside the top 25 | catching future leaders earlier (scored with the lead-time diagnostic) |
| `laggards_mega10_fq`, `munger_top50_fq` | the existing rules, keeping only names with stable or improving fundamentals | value trap filter (originals unchanged) |

Compounders get slower hold rules ▸ DEFAULT: monthly rebalance `while_listed` top 10 and `fixed_hold` 126
sessions. S&P 400 gets its own research pass, since its momentum runs are shorter.

## 6. Post-earnings drift (Phase 3, after Phase 2)

**Events.** Earnings timestamps from 8-K item 2.02 acceptance times (`submissions`, one call per company,
then the daily index). Per event: earnings-announcement return (day 0 to +1 abnormal return vs SPY),
volume vs its 20-day mean, gap-held (close day +3 vs day 0 open), and an earnings surprise without analyst
estimates: standardized unexpected EPS (this quarter vs the same quarter last year, scaled by the
volatility of that change over the last 8 quarters). ~5 y × 900 names ≈ 18 k events.

**Categories:** `pead_up` (top decile reaction + positive surprise + gap held), hold `fixed_hold` 42 and 63
sessions; `pead_down` mirror for §10. Research: `research/03-pead.md`.

## 7. Insider buying (Phase 4, after Phase 2)

**Data.** Form 4 open-market purchases (code P, acquired) into `insider_trades`: backfill 5 y from the SEC's
quarterly insider data sets; daily from the EDGAR daily index. Owner roles, value, % of holding increase,
10%-owner flag (ported from zacseidel/insiders' parser and scoring).

**Universe.** Insider buying is strongest in small companies, mostly outside the S&P 900. ▸ DEFAULT: insider
clusters anywhere join the `signals` universe (same path Congress / 13F names use: bars backfilled on entry),
with a minimum price and dollar volume.

**Categories:** `insider_clusters` (≥ 2 non-10%-owner insiders buying within 30 days, ≥ $100 k total),
`insider_ceo_cfo` (C-suite buys ≥ $250 k), and — your layering — **`insider_quality`** (clusters where
fundamentals are stable or improving) next to **`insider_turnaround`** (clusters where they are
deteriorating), so the "insiders buying a bad company to signal" case is measured rather than assumed.
Note: the insiders repo's performance page currently prices nothing (all 295 positions "Entry-session price
not available"); this replaces that evaluation with the shared engine.

## 8. Corporate actions as events (Phase 6)

From data already stored or from Phase 2: `div_initiators` (first dividend in ≥ 3 years), `div_raisers`
(raised ≥ 10%), `div_streak` (raised in each of the last 5 years), `spinoffs` (new securities spun off from
an S&P 900 parent — ticker events + Wikipedia change notes; hold `fixed_hold` 252), buyback acceleration
(from `shrinkers`). Splits are dropped: we only have execution dates, not announcements.

## 9. Short interest and short volume (Phase 7)

`short_interest` (twice monthly, ~2 calls per company, 2017 →, `available_at` = settlement + 8 business
days) and `short_volume` (daily, 2024 →). Used three ways: a **risk column** on every category list
(days to cover, % of float); `squeeze` category (days to cover ≥ 5 and price rank rising); and an input to
the shorts in §10.

## 10. Shorts (Phase 8)

**Instrument `short`**: sell at the same fills as long stock, pay dividends, earn the T-bill rate on proceeds
minus a borrow fee ▸ DEFAULT 0.5%/yr, 3%/yr when short interest > 10% of float; position capital = proceeds,
losses uncapped and reported as such. Later: long puts as the option version (the panel's put band is
70–102% of spot, enough for near-the-money puts).

**Categories:** `decliners` S&P 500 / 400 (worst 12-month return with rank still worsening, below the
200-day average, fundamentals decelerating), `pead_down`, bearish option flow.

**Evaluation:** standalone (vs SPY and vs −SPY) **and as a hedge**: a paired strategy = an existing long
strategy + an equal-dollar short basket, so we can see whether shorts cut drawdowns without giving back
the return. Expect shorts to lose in rising markets; the question is the drawdown trade.

## 11. Convergence (Phase 9, last)

`convergence`: names flagged by ≥ 2 independent families within 30 days — momentum, fundamentals, PEAD,
insiders, Congress, 13F, option flow. Ranked by the count, then by each family's as-of strength. Diagnostic:
does a second family add to the first family's result?

---

## 12. Order, size, open questions

| Phase | Work | Depends on | New storage | One-time fetch |
|---|---|---|---|---|
| 0 | Lab stage, since-added record, Context sources, research scaffold, lead-time metric | — | tiny | — |
| 1 | Option flow table + exploration + categories | 0 | ~20 MB | ~1.7 GB re-stream |
| 2 | EDGAR fundamentals + 6 category families | 0 | ~40 MB | ~0.5 GB |
| 3 | Earnings events + PEAD | 2 | ~2 MB | ~1,750 calls |
| 4 | Insider trades + 4 categories | 2 | ~10 MB | ~20 quarterly files |
| 5 | Adaptive IV option tier | 1 | — | — |
| 6 | Corporate-action events | 2 | tiny | — |
| 7 | Short interest / volume | 0 | ~15 MB | ~3,500 calls |
| 8 | Short instrument + decliners + hedged pairs | 2 (and 1, 3, 7 for inputs) | — | — |
| 9 | Convergence | all | — | — |

Phases 1 and 2 are independent and can be built in parallel. Daily run cost after all phases: a few
hundred extra EDGAR / Polygon calls and no extra downloads; disk ~90 MB more (72 GB free).

**Open questions**
1. Lab promotion rule (§2.3) — keep the default or set your own?
2. Insider names outside the S&P 900 (§7) — OK to add them to the `signals` universe?
3. Borrow fee for shorts (§10) — 0.5% / 3% defaults OK?
4. Hold rules for compounders (§5) — monthly `while_listed` and 6-month `fixed_hold` as the first two?
