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

## 3. Options flow and implied volatility (Phase 1) — built 2026-10-21

**Status.** `option_flow_daily` backfilled (501 sessions, 613 k rows, 2024-10-21 →); daily step
`option_flow` runs before `categories`. Research: `docs/research/01-option-flow.md`. Of 11 features,
none of the "unusual call buying" ones held up. Kept (both borderline on 2 years, so Lab):
- **IV ÷ realized vol, top decile → lags SPY ~1%/month** (out-of-sample t −4). The raw list is crowded
  by pending acquisitions (pinned price, collapsed realized vol); with realized vol ≥ 15% the effect
  holds (−0.7% in, −1.5% out). → `ivrich_sp900` (warning / short list) and IV-filtered Leaders /
  Rank Momentum (`mom12iv_sp500`, `mom12iv_sp400`, `rankmomiv_sp500`).
- **Inverted term structure (30-day IV > long-dated IV) → beats steep upward term** (~+0.8% in,
  +1.2% out per month) → `ivinverted_sp900`.

First results (2024-11 → 2026-10, partly in-sample): IV filter lifts S&P 400 Leaders top 5 to 29% CAGR
(17% unfiltered) and Rank Momentum top 5 to 97% (90%); S&P 500 Leaders top 5 80% (79%); next 5 worse.
Warning list 2% CAGR vs SPY 15%; inverted term 21% (Sharpe 0.51 vs SPY 0.63). Re-run the research in
~6 months to retest the near misses (OTM call surges, skew).


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

## 4. Implied-volatility method choice (Phase 5, after Phase 1) — tried and dropped 2026-10-21

**Outcome.** An Adaptive tier (per window: the base's Defensive method when implied ÷ realized vol was in
the top fifth of liquid names, Aggressive in the bottom fifth, else Balanced) had a lower Sharpe than the
plain Balanced tier on all four bases (`docs/research/05-adaptive-options.md`). Removed from the code
at the user's request (no benefit); the report stays as the record. Original plan below.


Add a fourth tier, **Adaptive**, to each option base (the three current tiers don't change). On each
window entry it picks the method from that day's IV state: IV high vs its own history or vs realized vol →
the base's CSP; IV low → its LEAP; in between → the diagonal or stock. ▸ DEFAULT signal: IV ÷ 20-day
realized vol (no 1-year look-back needed, so the whole 2-year history is testable). Evaluated in the option
grid first, then tracked.

---

## 5. Fundamentals (Phase 2) — the biggest enabler — built 2026-10-21

**Status.** `fundamental_facts`: 2.35 M XBRL facts for 1,387 companies (88% of the S&P 500, 91% of the
S&P 400; the rest are foreign / IFRS filers or use other tags). `market.data.fundamental_metrics`
derives quarters as first filed (YTD differencing, Q4 = FY − 9M or FY − three quarters) and per-filing
states usable the day after filing. Daily step `fundamentals` re-fetches the day's 10-K / 10-Q filers.
Research: `docs/research/02-fundamentals.md` (monthly, 2022-10 → 2026-10, in-sample before 2025).
- Survived: **margin expansion** (gross and operating, both indexes, stronger at 6 months) and
  **trailing earnings growth** (S&P 500 only).
- Did not: revenue / EPS acceleration, multiple expansion, share shrinkage; **steady growers reversed**
  in 2025–26 (top-vs-bottom −3.9% per quarter in the S&P 500).

Lab results from 2022-11-29 (the momentum lists' first date; 2025+ mostly out of sample):

| Strategy | CAGR | Sharpe | Worst | 2025+ | Compare |
|---|---|---|---|---|---|
| S&P 400 Emerging Leaders top 5 | 33.9% | 1.08 | −27% | 47.6% | S&P 400 Leaders 31.8% / 0.57 / −46%, 2025+ 24.7% |
| S&P 400 Fundamental Momentum top 5 | 35.6% | 0.87 | −33% | 60.2% | (from 2021-10, incl. 2022: 16.2% / 0.33 / −54%) |
| S&P 500 Fundamental Momentum top 5 | 33.6% | 0.67 | −39% | 48.7% | S&P 500 Leaders 60.1% / 0.96; SPY 20.4% |
| S&P 500 Re-rating top 5 | 30.1% | 0.61 | −35% | 25.2% | |
| Megacap Laggards, fundamentals filter | 36.5% | 1.19 | −29% | 38.4% | original 41.5% / 1.23 (filter hurt) |
| Steady Compounders S&P 500 / 400 | −5.2% / 7.0% | | −42% / −58% | | failed — dropped |

Lead time: Emerging Leaders' picks later joined the Leaders top 10 18–21% of the time, ~130 days early
(1% already there) — less often than Fast Rank Momentum (35–37%, ~100 days, 23% already there).


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

**Pruned 2026-10-21 (user, after the overview):** dropped Steady Compounders (both), S&P 400 Re-rating,
S&P 400 Share Shrinkers, and the fundamentals filter on Megacap Laggards and Munger Dip. Kept S&P 500
Re-rating and S&P 500 Share Shrinkers (beat SPY by ~2.7 points a year at the same Sharpe).

**Steady Leaders (added 2026-10-21, user's idea):** among S&P 500 ranks 6–50 by 12-month return, buy the 5
that spent the most of the last 26 weeks in the top 50 (`docs/research/07-steady-leaders.md`). Smoothness
measures (frog-in-the-pan, straight-line trend, up weeks) did not help; longevity did. From 2023-04: 49% a
year, Sharpe 0.96, vs 30% / 0.62 for the Leaders' ranks 6–10 (Leaders' top 5: 69% / 1.05).

## 6. Post-earnings drift (Phase 3, after Phase 2) — built 2026-10-21

**Status.** `earnings_events`: 31.6 k 8-K item 2.02 releases (1,382 companies, 2021 →) from EDGAR
submissions; daily step `earnings` re-reads the day's 8-K filers. EDGAR's JSON acceptance time is true UTC
for some filers and shifted 4–5 h late for others (Apple): after-close releases are corrected with the
17:30 filing-date rule; shifted pre-market ones stay a few hours late but react in the same session.
Fundamentals gained `sue` / `rev_sue` (seasonal random walk). Research `docs/research/03-earnings.md`
(17.9 k S&P 500 / 400 announcements): **no post-earnings drift** — no reaction or surprise feature survived;
big up-moves slightly reverse, big down-moves drifted lower before 2025 and bounced after. Kept as a Lab
pair to build a live record: `pead_up_sp900` 6.5% CAGR, `pead_down_sp900` 4.2%, SPY 12.2% (2021-11 →).


**Events.** Earnings timestamps from 8-K item 2.02 acceptance times (`submissions`, one call per company,
then the daily index). Per event: earnings-announcement return (day 0 to +1 abnormal return vs SPY),
volume vs its 20-day mean, gap-held (close day +3 vs day 0 open), and an earnings surprise without analyst
estimates: standardized unexpected EPS (this quarter vs the same quarter last year, scaled by the
volatility of that change over the last 8 quarters). ~5 y × 900 names ≈ 18 k events.

**Categories:** `pead_up` (top decile reaction + positive surprise + gap held), hold `fixed_hold` 42 and 63
sessions; `pead_down` mirror for §10. Research: `research/03-pead.md`.

## 7. Insider buying (Phase 4, after Phase 2) — tried and dropped 2026-10-21

**Outcome.** Form 4 purchases 2021 → 2026 (SEC quarterly data sets + parsed filings) at S&P 500 / 400
companies showed little signal vs the average member (slightly positive before 2025, negative after);
quality vs turnaround (fundamentals) did not separate; all four Lab lists trailed SPY
(`docs/research/04-insiders.md`). Removed — code, daily step and the 138 k-row table — at the user's
request (lots of data, no benefit). Untested: small companies outside the S&P 900. Original plan below.


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

## 8. Corporate actions as events (Phase 6) — built 2026-10-21 (Dividend Raisers)

**Outcome.** `docs/research/06-corporate-actions.md` (S&P 500 / 400, 2021-10 → 2026-10, vs the average
member; events dated by the announcement — dividends now store `declared` and `frequency`): raises ≥ 10%
beat the average member (+2.0% / +3.5% over 126 sessions, in / out); as a strategy (total return) it matched
SPY (12.2% vs 12.1% a year, smaller worst drop) → kept as the Lab category **Dividend Raisers** (user's call). Small raises lagged; **cuts ≥ 10% lagged badly (−6% / −12%)** → input for
the shorts phase. Initiations, specials: nothing; spinoffs: big but only 13 events. Original plan below.


From data already stored or from Phase 2: `div_initiators` (first dividend in ≥ 3 years), `div_raisers`
(raised ≥ 10%), `div_streak` (raised in each of the last 5 years), `spinoffs` (new securities spun off from
an S&P 900 parent — ticker events + Wikipedia change notes; hold `fixed_hold` 252), buyback acceleration
(from `shrinkers`). Splits are dropped: we only have execution dates, not announcements.

## 9. Short interest and short volume (Phase 7) — built 2026-10-21

**Status.** `short_interest` table (215 k readings, 1,527 companies, 2020-06 →; available = settlement + 8
business days); daily step `short_interest` (one market-wide call per new settlement date). Research
`docs/research/08-short-interest.md`: **days to cover** predicts underperformance in both indexes and
both halves (top vs bottom fifth ≈ −2% to −3% over 63 sessions; among momentum leaders up to −17% over
126 sessions in 2025–26); short % of shares and its change: nothing consistent. Kept: **S&P 500 Leaders,
Short-Interest Filter** (skip the top fifth of days to cover) — 68% a year, Sharpe 1.07 vs 60% / 0.96
unfiltered (2025+: 116% vs 90%). The same filter hurt S&P 400 Leaders and S&P 500 Rank Momentum → dropped.
High days to cover is a short-candidate input for Phase 8. Short volume not used.


`short_interest` (twice monthly, ~2 calls per company, 2017 →, `available_at` = settlement + 8 business
days) and `short_volume` (daily, 2024 →). Used three ways: a **risk column** on every category list
(days to cover, % of float); `squeeze` category (days to cover ≥ 5 and price rank rising); and an input to
the shorts in §10.

## 10. Shorts (Phase 8) — built 2026-10-21

**Status.** Engine: instrument `short` (rf on proceeds − basket total return, so dividends are paid, − borrow;
default 0.5%/yr) and `overlay` strategies (a long fully invested + a weight of capital shorted in a short
strategy's basket). Research `docs/research/09-shorts.md` scored seven candidate lists short, paired vs SPY,
and as a 30% hedge on S&P 500 Leaders (short-interest filter). In this rising market most lists lag SPY but
still rise, so shorting them lost money (decliners −16%/yr, heavily shorted −8%, weak earnings −5%, IV
warning −4%) and hedging with them cut returns. **Dividend cuts are the exception**: the stocks fell ~7% a
year; short alone ≈ T-bill (3%); as a 30% hedge, 73% a year / Sharpe 1.17 vs 68% / 1.08 unhedged, better in
both halves, same worst drop. Only 82 cuts (~8 open at a time), so thin. Kept (Lab): **Dividend Cutters
(short)** and **S&P 500 Leaders SI filter + 30% Dividend Cutters short**.


**Instrument `short`**: sell at the same fills as long stock, pay dividends, earn the T-bill rate on proceeds
minus a borrow fee ▸ DEFAULT 0.5%/yr, 3%/yr when short interest > 10% of float; position capital = proceeds,
losses uncapped and reported as such. Later: long puts as the option version (the panel's put band is
70–102% of spot, enough for near-the-money puts).

**Categories:** `decliners` S&P 500 / 400 (worst 12-month return with rank still worsening, below the
200-day average, fundamentals decelerating), `pead_down`, bearish option flow.

**Evaluation:** standalone (vs SPY and vs −SPY) **and as a hedge**: a paired strategy = an existing long
strategy + an equal-dollar short basket, so we can see whether shorts cut drawdowns without giving back
the return. Expect shorts to lose in rising markets; the question is the drawdown trade.

## 11. Convergence (Phase 9, last) — researched 2026-10-21, strategies dropped

**Status.** `docs/research/10-convergence.md`: six families (momentum, fundamentals, reversion, events,
options, smart money) from the stored lists. Over the next 63 sessions vs the average member: one family
+1.3% / +0.9% (before / after 2025), two +1.8% / +6.3%, three or more +5.2% / +11.5%; momentum + fundamentals
the strongest consistent pair. Lab: **Convergence** (most families, ≥ 2) and **Momentum + Fundamentals**; as
top-5 strategies from 2022-11 they returned 39% / 38% a year (Sharpe 0.74 / 0.68) vs SPY 20% (0.97) and S&P
500 Leaders 60% (0.96) — dropped at the user's call (no edge over the momentum lists they overlap with);
the report is the record.


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

Phases 1 and 2 are independent and can be built in parallel. **Rule from 2026-10-21 (user): research
first; build Lab categories only for ideas that show a benefit — no Lab entries just to keep a record.** Daily run cost after all phases: a few
hundred extra EDGAR / Polygon calls and no extra downloads; disk ~90 MB more (72 GB free).

**Open questions**
1. Lab promotion rule (§2.3) — keep the default or set your own?
2. Insider names outside the S&P 900 (§7) — OK to add them to the `signals` universe?
3. Borrow fee for shorts (§10) — 0.5% / 3% defaults OK?
4. Hold rules for compounders (§5) — monthly `while_listed` and 6-month `fixed_hold` as the first two?
