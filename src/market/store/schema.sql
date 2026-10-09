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

CREATE TABLE IF NOT EXISTS ticker_history (
    security_id   VARCHAR NOT NULL,
    ticker        VARCHAR NOT NULL,
    valid_from    DATE NOT NULL,
    valid_to      DATE,                    -- exclusive; NULL = current
    PRIMARY KEY (security_id, valid_from)
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
