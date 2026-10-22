# Plan — one model for strategies, one path to the Newsfeed (2026-10-22)

**Status (2026-10-22): built.** Decisions taken:
- D1 (a): best variants are judged on their own history, so the IV variants (two years of options data) can win.
  SPY Rank Momentum with the IV filter is followed and tracked going forward.
- D2: enter at 1.10×, leave below 1.00×.
- D3: Steady Leaders is its own strategy, not a Leaders variant (it draws on the top 50).
- D4: reports stay Tuesday and Friday (Monday and Thursday closes). Index membership is now checked against Wikipedia
  on every run; Congress and 13F checks stay daily.
- Short display names: SPY = S&P 500, MDY = S&P 400, Ldrs, Rank Mom, Fund. …

Feed today: SPY Ldrs · SI (1.11×), SPY Rank Mom · IV (1.99×), MDY Improving Fund. & Rank (1.23×). Megacap Laggards
(1.07×) left the feed because it never reached the 1.10× entry bar.

Replaces the Lab / Strategies / Categories split with the user's model. Built on review 04
(`docs/reviews/04-alignment-and-data-plans.md`). The API-plan question is set aside for now.

## 1. The model

```
Universe          S&P 500 · S&P 400 · Megacap · S&P 900 · Congress / 13F
  └ Strategy      one idea on one universe: "S&P 500 Leaders", "S&P 500 Rank Momentum", "S&P 400 Fundamentals" …
      └ Variant   the base list, or the base list plus one filter (short interest, IV, stall, RSI …); slot (top 5 / next 5); hold rule
          └ Evaluation   the same metrics for every variant; SPY over the same dates
Champion          the best variant of each strategy, chosen by a fixed rule (§3)
Newsfeed          the champions that beat SPY by a margin, merged into one portfolio with report-by-report changes
```

- **"Lab" goes away as a place.** Every variant is evaluated and shown in one place. What "lab" meant becomes a field:
  a variant's `added` date marks where its out-of-sample record starts ("on trial since …"). Stages reduce to
  `active | retired`.
- **"Category" stops being a user-facing word.** A category is how a variant's list is computed, so its page becomes
  the List tab of the variant's page.

## 2. Strategies and their variants (today's 42 stock strategies)

Sharpe is measured over the dates every variant in the strategy shares (top 5 slots), so variants are compared fairly.

| Universe | Strategy | Variants (Sharpe, common dates) | Champion → vs SPY over its own history |
|---|---|---|---|
| S&P 500 | **Leaders** (12-month momentum) | SI filter 1.26 · Isolated Stall 1.12 · Reasonable Growth (RSI) 1.09 · IV filter 1.02 · base 1.01 · Steady 0.72 | SI filter: 1.09 vs 0.99 = **1.11×** ✅ |
| S&P 500 | **Rank Momentum** | IV filter 1.29 · base 1.20 · Fast (1/3/6) 0.82 | IV filter: 1.29 vs 0.65 = **1.99×** ✅ (2-year history only, see D1) |
| S&P 500 | Fundamentals | Share Shrinkers 0.73 · Fund. Momentum 0.67 · Re-rating 0.59 | Shrinkers 0.87× |
| S&P 400 | Leaders | IV filter 0.44 · Reasonable Growth 0.32 · base 0.25 | 0.68× |
| S&P 400 | Rank Momentum | base 0.38 · Fast 0.25 | 0.39× |
| S&P 400 | **Fundamentals** | Improving Fund. & Rank 1.21 · Emerging 1.08 · Fund. Momentum 0.88 | Improving: 1.21 vs 0.99 = **1.23×** ✅ |
| Megacap | Leaders | base 0.89 | 0.90× |
| Megacap | Laggards | top 2, hold 21 sessions 1.03 | **1.07×** (in the feed today, out under a 10% rule) |
| Megacap | Munger Dip | 0.53 | 0.65× |
| S&P 900 | Dividend Raisers / Cutters (short) / Inverted IV term | 0.41 / — / 0.52 | below SPY |
| Congress / 13F | Buys · Holdings / Buys · Drivers | ≤ 0.88 | below SPY (short histories) |

**Next 5 slots** (ranks 6–10) stay as variant rows for reference but can't be champions. They are a deeper slot of the
same list, not an alternative to it.

**Result under the proposed rules:** the feed holds three lists:
- S&P 500 Leaders with the short-interest filter;
- S&P 500 Rank Momentum with the IV filter;
- S&P 400 Improving Fundamentals & Rank.

Under the recommended D1 (b), Rank Momentum drops out and the feed holds two. Megacap Laggards and Steady Leaders drop
out either way.

## 3. Rules

1. **Champion.** The variant with the highest Sharpe over the strategy's common dates (top-5 slots only).
   - A filter must beat the base by ≥ 0.05 Sharpe to win; otherwise the simpler base wins.
   - This is the same tie margin the Options page uses (`SHARPE_TIE`).
   - Re-chosen at each export, with no switch unless the margin holds for N runs. N is a decision; default 1.
2. **Feed inclusion.** The champion's Sharpe ≥ 1.10 × SPY's Sharpe over the same dates.
   - It stays in until it falls below 1.00× (hysteresis).
   - Half-Kelly > 0, so ≥ 20 closed trades.
   - Hold rule `while_listed` or `fixed_hold`.
3. **One SPY number per comparison.** `benchmark_sharpe` is stored with every metrics row. The Strategies table, the
   strategy pages and the feed all read it; nobody recomputes it.

## 4. Pages

### Overview (`#/`), "where things stand"
Today it is the same table as Strategies plus latest-report cards. New layout:
- **Headline:** the latest feed report: date, N buys / sells / trims, the current allocation (stock → weight, the SPY
  remainder), and a link to the Newsfeed.
- **Scoreboard:** one row per strategy, grouped by universe. Columns:
  - champion variant;
  - Sharpe;
  - SPY Sharpe on the same dates;
  - a ratio bar with the 1.10× line;
  - CAGR and worst drawdown;
  - an In the feed badge.

  This is the one-glance answer to "which ideas beat SPY".
- **Latest lists:** report cards only for the feed's lists, each showing its base list with the filtered names struck
  through (below).

### Newsfeed (`#/news`), "what to do"
Keep today's structure, with these changes:
- **"Lists considered" becomes "Strategies in the feed".** One row per strategy, naming its champion and why it won
  (e.g. "SI filter beats Leaders 1.26 vs 1.01 on the same dates"). A collapsed "not in the feed" list shows each
  strategy's ratio.
- **Each list** shows the base list's top 5 plus enough names to fill the slots:
  - filtered-out names are ~~struck through~~ with the filter's reason ("heavily shorted: 7.2 days to cover, top 4%");
  - the names that move up to fill the slots are marked "in for a filtered name".
- **Allocation and Report history** stay as they are (Buy / Add / Trim / Sell / Hold with reasons and closed results).
  Optional: group Tue + Fri into one weekly card (D4).

### Strategies (`#/strategies`), "everything we track"
- Grouped by universe. Each strategy is a card with its variants table:
  - variant;
  - filter;
  - Sharpe over the common dates;
  - Sharpe over its own history vs SPY on the same dates;
  - CAGR;
  - drawdown;
  - half-Kelly;
  - "on trial since" (the `added` date);
  - a champion marker.
- Window selector: Since inception / 3Y / 1Y, all with SPY on the same dates.
- A variant's page combines today's strategy page and category page:
  - Performance tab: chart, metrics and trades;
  - List tab: latest list with struck-through filtered names, membership heatmap and lead time;
  - out-of-sample since `added`.

### Lab (`#/lab`): removed
- Its out-of-sample column moves to Strategies.
- Its research links move to Methodology. Each research report in `docs/research/` gets a one-line summary there.
- `#/lab` redirects to `#/strategies`.

### Categories (`#/categories`): folded into the variant pages' List tab
Redirect to `#/strategies`. The Reports page (all lists on a report date) stays.

### Options: unchanged for now (API question set aside)
Its bases should follow the champions later.

## 5. Engine and data changes

1. **Declare strategy and filter on the category.** For example:
   ```python
   @category("mom12si_sp500", ..., strategy="sp500_leaders", base="mom12_sp500", filter="Short interest")
   ```
   Base categories declare `strategy=` only. These replace the `group` field and `newsfeed.candidates`.

   The variants of S&P 500 Leaders, by base:
   - base `mom12_sp500`: Stall, SI and IV filters;
   - its own unfiltered 12-month ranking: Reasonable Growth;
   - a separate signal: Steady.

   Where a variant isn't a filter of another list, it has no `base`, and the List tab shows it plainly.
2. **Store filtered-out names (generic strikethrough).** A filter variant also returns the base names it skipped, each
   with an `excluded` reason. They are stored in `category_snapshots` with `rank` NULL.
   - The engine ignores them; pages show them struck through.
   - This replaces the special-case `filter_reading()` code in `export_newsfeed.py`, which only knows SI and IV, and
     covers stall, RSI and any future filter.
   - Changing these categories' functions changes their `version`, so the daily run rebuilds them (~minutes). Their
     kept names, and so their results, must come out identical; this needs a test.
3. **Metrics.**
   - `performance()` stores `benchmark_sharpe` / `benchmark_max_drawdown`.
   - The engine adds a per-strategy `common` window (each variant over the strategy's shared dates).
   - A small `champions` step after evaluation writes champion, ratio and in-feed, with the hysteresis state kept in the
     DB.
4. **Config.** `strategies.yaml` drops `stage: lab` (keeps `added`; `retired` stays). `config.yaml → newsfeed` keeps:
   - sizing (`cap`, `min_change`, `reports`, `depth`);
   - new: `margin_in: 1.10`, `margin_out: 1.00`, `champion_tie: 0.05`.
5. **Export.** `meta.json` gains `strategies_by_universe` (strategy → variants, champion, in_feed). `news.json` is built
   from the champions. The Lab/Categories split in `app.js` goes.
6. **Docs.** HANDOFF, Methodology page text, CLAUDE-facing notes.

## 6. Order of work

| Step | What | Check |
|---|---|---|
| 1 | Category `strategy/base/filter` fields; stored `benchmark_sharpe` | tests; one SPY number on both pages |
| 2 | Filter variants store excluded names; generic strikethrough | rebuilt categories give identical kept lists and NAVs |
| 3 | Common-window metrics, champions step, rule-based feed (replaces candidates) | feed matches §2 / D1 on today's data |
| 4 | Strategies page by universe → strategy → variants; variant page = performance + list | browser check |
| 5 | Overview rebuilt (headline, scoreboard, feed lists); Newsfeed list display with strikethrough | browser check, phone width |
| 6 | Remove Lab and Categories pages (redirects); research links on Methodology; docs | full run + export |

## 7. Decisions needed

- **D1 – Young histories.** The Rank Momentum champion (IV filter) has only 2 years of data, a stretch when SPY's Sharpe
  was 0.65. The base Rank Momentum over its full 4 years is 1.00× SPY. Options:
  - (a) Judge the champion on its own history. The feed holds three lists (§2) but favors young variants.
  - (b) A variant needs ≥ 3 years of history to be champion. Younger variants are shown and tracked, and become eligible
    when they reach 3 years. Today the feed holds two lists, S&P 500 Leaders SI and S&P 400 Improving: the IV variant
    isn't eligible, and the Rank Momentum base is 1.00×.
  - (c) Judge each strategy by its base variant over its full history. This leaves the feed nearly empty: the S&P 500
    Leaders base is 1.00× and the S&P 400 Fund. Momentum base 0.70×.

  Recommended: (b). It is the same yardstick for everyone, with no window bias, and the IV variants become eligible
  in late 2027.
- **D2 – Margin.** 1.10× in / 1.00× out (recommended), or a single 1.10×.
- **D3 – Steady Leaders.** Treat it as a variant of S&P 500 Leaders (recommended), or as its own strategy.
- **D4 – Report cadence.** Keep Tue + Fri cards (recommended: the trades happen then), or merge them into weekly cards.
