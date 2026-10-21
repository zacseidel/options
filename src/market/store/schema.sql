-- market.duckdb schema (PLAN §4). Idempotent: every statement is CREATE ... IF NOT EXISTS.
-- Tables are added here as each phase lands; outputs (snapshots, trades, NAV) come later.

-- ------------------------------------------------------------------ operations
CREATE TABLE IF NOT EXISTS fetch_log (
    source      VARCHAR NOT NULL,          -- e.g. 'grouped_daily', 'options_day', 'wiki_sp500'
    key         VARCHAR NOT NULL,          -- e.g. '2026-10-07'
    fetched_at  TIMESTAMP NOT NULL,
    rows        INTEGER,
    immutable   BOOLEAN NOT NULL,          -- closed sessions / expired data: never fetch again
    PRIMARY KEY (source, key)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id        VARCHAR PRIMARY KEY,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    status        VARCHAR,
    data_through  DATE,
    code_version  VARCHAR,
    summary       JSON
);

-- ------------------------------------------------------------------ reference
CREATE TABLE IF NOT EXISTS securities (
    security_id   VARCHAR PRIMARY KEY,     -- composite FIGI when known, else 'T:<ticker>:<first_seen>'
    figi          VARCHAR,
    ticker        VARCHAR NOT NULL,        -- current / last ticker
    name          VARCHAR,
    type          VARCHAR,                 -- CS, ETF, ADRC, ...
    exchange      VARCHAR,
    list_date     DATE,
    delist_date   DATE
);

-- Which security used a ticker when. Several rows may cover the same (ticker, date); the
-- lowest priority wins: 1 = ticker-change events / current ticker, 2 = other tickers observed
-- for the same FIGI, 3 = synthetic stand-in for an index member Polygon has no record of.
CREATE TABLE IF NOT EXISTS ticker_history (
    security_id   VARCHAR NOT NULL,
    ticker        VARCHAR NOT NULL,
    valid_from    DATE NOT NULL,
    valid_to      DATE,                    -- exclusive; NULL = current
    priority      TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS calendar (
    date          DATE PRIMARY KEY,
    is_open       BOOLEAN NOT NULL,
    early_close   BOOLEAN NOT NULL DEFAULT FALSE
);

-- ------------------------------------------------------------------ universes
-- Membership as intervals: a member from valid_from (inclusive) to valid_to (exclusive).
CREATE TABLE IF NOT EXISTS universe_membership (
    universe      VARCHAR NOT NULL,        -- 'sp500', 'sp400'
    ticker        VARCHAR NOT NULL,        -- ticker as recorded by the source at the time
    security_id   VARCHAR,                 -- resolved via ticker_history once securities load
    valid_from    DATE,                    -- NULL = member since before the source's history
    valid_to      DATE,                    -- NULL = current member
    source        VARCHAR NOT NULL         -- 'wikipedia', 'ssga'; rows are replaced per (universe, source)
);

-- Raw index change events as published (audit trail for the membership replay).
CREATE TABLE IF NOT EXISTS universe_changes (
    universe      VARCHAR NOT NULL,
    date          DATE NOT NULL,
    action        VARCHAR NOT NULL,        -- 'add' | 'drop'
    ticker        VARCHAR NOT NULL,
    name          VARCHAR,
    reason        VARCHAR,
    source        VARCHAR NOT NULL,
    PRIMARY KEY (universe, date, action, ticker, source)
);

-- SSGA holdings weights, stored only on days the holdings file changes.
CREATE TABLE IF NOT EXISTS universe_weights (
    universe      VARCHAR NOT NULL,
    date          DATE NOT NULL,
    ticker        VARCHAR NOT NULL,
    name          VARCHAR,
    weight        DOUBLE,
    PRIMARY KEY (universe, date, ticker)
);

-- ------------------------------------------------------------------ migrations (idempotent)
ALTER TABLE securities ADD COLUMN IF NOT EXISTS cik VARCHAR;

-- ------------------------------------------------------------------ market data
CREATE TABLE IF NOT EXISTS bars_daily (
    security_id   VARCHAR NOT NULL,
    date          DATE NOT NULL,
    open          DOUBLE,
    high          DOUBLE,
    low           DOUBLE,
    close         DOUBLE NOT NULL,
    volume        DOUBLE,
    vwap          DOUBLE,
    PRIMARY KEY (security_id, date)
);                                         -- unadjusted; adjust on read (PLAN §2.5)

CREATE TABLE IF NOT EXISTS splits (
    security_id   VARCHAR NOT NULL,
    ex_date       DATE NOT NULL,
    split_from    DOUBLE NOT NULL,
    split_to      DOUBLE NOT NULL,
    PRIMARY KEY (security_id, ex_date)
);

CREATE TABLE IF NOT EXISTS dividends (
    security_id   VARCHAR NOT NULL,
    ex_date       DATE NOT NULL,
    pay_date      DATE,
    amount        DOUBLE NOT NULL,
    kind          VARCHAR,                 -- CD regular, SC special, ...
    PRIMARY KEY (security_id, ex_date, kind)
);

-- Point-in-time company market cap (quarterly), scaled daily by adjusted price for ranking.
CREATE TABLE IF NOT EXISTS market_caps (
    security_id   VARCHAR NOT NULL,
    date          DATE NOT NULL,
    market_cap    DOUBLE,
    shares        DOUBLE,
    PRIMARY KEY (security_id, date)
);

-- ------------------------------------------------------------------ categories & evaluation
-- One row per (category, report date, security): the ranked list as of that report.
CREATE TABLE IF NOT EXISTS category_snapshots (
    category_id   VARCHAR NOT NULL,
    report_date   DATE NOT NULL,           -- signals are known before this session opens
    as_of         DATE NOT NULL,           -- last session whose data was used
    security_id   VARCHAR NOT NULL,
    ticker        VARCHAR,                 -- ticker as of the report (display)
    rank          INTEGER NOT NULL,
    score         DOUBLE,
    features      JSON,
    origin        VARCHAR NOT NULL,        -- 'backtest' | 'live' | 'legacy'
    version       VARCHAR NOT NULL,
    PRIMARY KEY (category_id, report_date, security_id, origin)
);

CREATE TABLE IF NOT EXISTS trades (
    strategy_id       VARCHAR NOT NULL,
    trade_id          VARCHAR NOT NULL,
    security_id       VARCHAR NOT NULL,
    ticker            VARCHAR,
    signal_date       DATE NOT NULL,
    entry_date        DATE NOT NULL,
    entry_price       DOUBLE NOT NULL,     -- split-adjusted fill
    exit_signal_date  DATE,
    exit_date         DATE,
    exit_price        DOUBLE,
    exit_reason       VARCHAR,
    return_price      DOUBLE,              -- price return of the trade (fraction)
    return_total      DOUBLE,              -- incl. dividends
    status            VARCHAR NOT NULL,    -- 'open' | 'closed'
    PRIMARY KEY (strategy_id, trade_id)
);

CREATE TABLE IF NOT EXISTS nav_daily (
    strategy_id   VARCHAR NOT NULL,
    date          DATE NOT NULL,
    nav           DOUBLE NOT NULL,         -- total-return basis, starts at 100
    nav_price     DOUBLE NOT NULL,         -- price-return basis
    positions     INTEGER NOT NULL,
    PRIMARY KEY (strategy_id, date)
);

CREATE TABLE IF NOT EXISTS strategy_metrics (
    strategy_id   VARCHAR NOT NULL,
    window_name   VARCHAR NOT NULL,        -- 'all', '3y', '1y', 'ytd', ...
    metrics       JSON NOT NULL,
    computed_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (strategy_id, window_name)
);

-- ------------------------------------------------------------------ smart money (derived; raw ledgers stay in smartmoney)
-- One completed follow-the-filing holding period per 13F book: bought the session after the
-- filing, sold the session after the fund's next filing. Prices are not kept.
CREATE TABLE IF NOT EXISTS fund_periods (
    cik           BIGINT NOT NULL,
    accession     VARCHAR,
    entry         DATE NOT NULL,
    exit          DATE NOT NULL,
    ret           DOUBLE NOT NULL,         -- value-weighted return of the priced book
    spy_ret       DOUBLE NOT NULL,
    coverage      DOUBLE NOT NULL,         -- priced value / reported value
    n_priced      INTEGER,
    n_total       INTEGER,
    book          DOUBLE,
    PRIMARY KEY (cik, entry)
);

-- Completed periods whose book had nothing we could price (no holding maps to a ticker), so the
-- daily run doesn't refetch their sessions forever.
CREATE TABLE IF NOT EXISTS fund_periods_unpriced (
    cik           BIGINT NOT NULL,
    entry         DATE NOT NULL,
    checked_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (cik, entry)
);

-- Position weights and returns for funds that rank at some report date (alpha attribution).
CREATE TABLE IF NOT EXISTS fund_period_positions (
    cik           BIGINT NOT NULL,
    entry         DATE NOT NULL,
    ticker        VARCHAR NOT NULL,
    weight        DOUBLE NOT NULL,
    ret           DOUBLE NOT NULL,
    PRIMARY KEY (cik, entry, ticker)
);

-- Point-in-time leaderboards (Congress members, 13F funds) per report date: top N only.
CREATE TABLE IF NOT EXISTS entity_scores (
    kind          VARCHAR NOT NULL,        -- 'congress' | 'hedge'
    report_date   DATE NOT NULL,
    entity_id     VARCHAR NOT NULL,        -- member slug | CIK
    name          VARCHAR,
    rank          INTEGER NOT NULL,
    score         DOUBLE,                  -- dollar-weighted alpha | follow-the-filing alpha
    features      JSON,
    PRIMARY KEY (kind, report_date, entity_id)
);

-- ------------------------------------------------------------------ options (PLAN §4)
-- The option panel: rows from the daily OPRA day-aggregates file for the select option set,
-- kept only inside the strike/DTE bands and only around the periods a name is held.
CREATE TABLE IF NOT EXISTS option_bars (
    session       DATE NOT NULL,
    root          VARCHAR NOT NULL,        -- OCC root (ticker without dots)
    expiry        DATE NOT NULL,
    kind          VARCHAR NOT NULL,        -- 'C' | 'P'
    strike        DOUBLE NOT NULL,
    open          REAL,
    close         REAL,
    volume        INTEGER,
    transactions  INTEGER
);

-- Which (session, root) pairs have been streamed into option_bars (0 rows is still covered).
CREATE TABLE IF NOT EXISTS option_coverage (
    session       DATE NOT NULL,
    root          VARCHAR NOT NULL,
    rows          INTEGER NOT NULL,
    PRIMARY KEY (session, root)
);

-- Option legs behind each option-strategy trade (one window can hold several legs over time).
CREATE TABLE IF NOT EXISTS option_legs (
    strategy_id   VARCHAR NOT NULL,
    trade_id      VARCHAR NOT NULL,
    leg           INTEGER NOT NULL,
    kind          VARCHAR NOT NULL,        -- 'C' | 'P' | 'S' (shares)
    side          VARCHAR NOT NULL,        -- 'long' | 'short'
    expiry        DATE,
    strike        DOUBLE,
    open_date     DATE NOT NULL,
    open_price    DOUBLE,                  -- per share/contract-share, after the haircut
    open_delta    DOUBLE,
    open_iv       DOUBLE,
    close_date    DATE,
    close_price   DOUBLE,
    close_reason  VARCHAR,
    quantity      DOUBLE                   -- shares-equivalent per $1 of window capital
);

-- ------------------------------------------------------------------ option flow (PLAN-signals §3)
-- One row per underlying per session, summarized from the whole OPRA day-aggregates file for every
-- security we price (not just the option set). Volumes are contracts; premium is dollars traded
-- (volume × close × 100). IVs are Black-Scholes from closing prices, volume-weighted.
CREATE TABLE IF NOT EXISTS option_flow_daily (
    session          DATE NOT NULL,
    security_id      VARCHAR NOT NULL,
    root             VARCHAR NOT NULL,
    call_volume      INTEGER,
    put_volume       INTEGER,
    call_premium     DOUBLE,
    put_premium      DOUBLE,
    otm_call_volume  INTEGER,                 -- calls ≤ 30 DTE, strike 100–115% of spot
    otm_put_volume   INTEGER,                 -- puts ≤ 30 DTE, strike 85–100% of spot
    contracts        INTEGER,                 -- distinct contracts traded
    iv30             REAL,                    -- ATM (95–105%), 20–45 DTE, out-of-the-money side
    iv_long          REAL,                    -- ATM (90–110%), 120–400 DTE
    skew             REAL,                    -- put IV (88–95%) minus call IV (105–112%), 20–60 DTE
    PRIMARY KEY (session, security_id)
);

-- Sessions whose file has been summarized into option_flow_daily (and for how many underlyings).
CREATE TABLE IF NOT EXISTS option_flow_sessions (
    session       DATE PRIMARY KEY,
    underlyings   INTEGER NOT NULL,
    computed_at   TIMESTAMP NOT NULL
);

-- ------------------------------------------------------------------ fundamentals (PLAN-signals §5)
-- XBRL facts from EDGAR companyfacts for the metrics in market.data.fundamentals.CONCEPTS, every
-- filing that reported them (10-K / 10-Q and amendments), periods ending 2015 or later. `filed` is
-- the EDGAR filing date; a value is usable from the next session (point-in-time rule).
CREATE TABLE IF NOT EXISTS fundamental_facts (
    cik           BIGINT NOT NULL,
    metric        VARCHAR NOT NULL,        -- our name (revenue, net_income, ...)
    concept       VARCHAR NOT NULL,        -- the XBRL tag it came from
    priority      TINYINT NOT NULL,        -- alias order within the metric (0 = preferred)
    start         DATE,                    -- NULL for point-in-time (balance-sheet) values
    "end"         DATE NOT NULL,
    value         DOUBLE NOT NULL,
    form          VARCHAR NOT NULL,
    filed         DATE NOT NULL,
    accn          VARCHAR NOT NULL
);

-- ------------------------------------------------------------------ earnings events (PLAN-signals §6)
-- 8-K filings with item 2.02 (results of operations) from EDGAR submissions. `accepted` is EDGAR's
-- acceptance time in US/Eastern; it decides whether the market first reacts that session or the next.
CREATE TABLE IF NOT EXISTS earnings_events (
    cik           BIGINT NOT NULL,
    accn          VARCHAR PRIMARY KEY,
    filed         DATE NOT NULL,
    accepted      TIMESTAMP NOT NULL,      -- US/Eastern, naive
    items         VARCHAR NOT NULL
);

-- ------------------------------------------------------------------ insider purchases (PLAN-signals §7)
-- Open-market purchases (Form 4, non-derivative, code P, acquired) by any reporting owner of any issuer.
-- source: 'dataset' = SEC quarterly insider data sets; 'xml' = parsed from the filing (recent days).
CREATE TABLE IF NOT EXISTS insider_trades (
    accn          VARCHAR NOT NULL,
    seq           INTEGER NOT NULL,        -- transaction number within the filing
    issuer_cik    BIGINT NOT NULL,
    issuer_name   VARCHAR,
    ticker        VARCHAR,
    owner_cik     BIGINT,
    owner_name    VARCHAR,
    is_director   BOOLEAN,
    is_officer    BOOLEAN,
    is_ten_pct    BOOLEAN,
    officer_title VARCHAR,
    trans_date    DATE NOT NULL,
    filed         DATE NOT NULL,
    shares        DOUBLE,
    price         DOUBLE,
    value         DOUBLE,
    shares_after  DOUBLE,
    direct        VARCHAR,                 -- 'D' direct | 'I' indirect
    plan_10b5_1   BOOLEAN,
    source        VARCHAR NOT NULL,
    PRIMARY KEY (accn, seq)
);
