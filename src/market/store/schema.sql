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
