-- bhavkit schema v2
-- deliverable_daily PK widened to (symbol, series, date) because NSE's
-- sec_bhavdata_full file carries one row per (symbol, series) including
-- inactive series (N1..N7) alongside EQ.
-- All tables are created idempotently (IF NOT EXISTS) and versioned via the
-- schema_migrations table managed in db.py.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bhav_daily (
    symbol VARCHAR NOT NULL,
    series VARCHAR NOT NULL,
    date DATE NOT NULL,
    prev_close DOUBLE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    last DOUBLE,
    close DOUBLE,
    avg_price DOUBLE,
    total_traded_quantity BIGINT NOT NULL DEFAULT 0,
    turnover DOUBLE NOT NULL DEFAULT 0,
    no_of_trades BIGINT NOT NULL DEFAULT 0,
    delivery_qty BIGINT NOT NULL DEFAULT 0,
    delivery_pct DOUBLE NOT NULL DEFAULT 0,
    source_file VARCHAR NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, series, date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    index_name VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT NOT NULL DEFAULT 0,
    turnover DOUBLE NOT NULL DEFAULT 0,
    source_file VARCHAR NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (index_name, date)
);

CREATE TABLE IF NOT EXISTS fo_daily (
    instrument VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    expiry_date DATE NOT NULL,
    option_type VARCHAR,
    strike_price DOUBLE,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    settle_price DOUBLE,
    contracts BIGINT NOT NULL DEFAULT 0,
    value DOUBLE NOT NULL DEFAULT 0,
    open_interest BIGINT NOT NULL DEFAULT 0,
    change_in_oi BIGINT NOT NULL DEFAULT 0,
    source_file VARCHAR NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (instrument, symbol, expiry_date, option_type, strike_price, date)
);

CREATE TABLE IF NOT EXISTS deliverable_daily (
    symbol VARCHAR NOT NULL,
    series VARCHAR NOT NULL,
    date DATE NOT NULL,
    isin VARCHAR,
    quantity_traded BIGINT NOT NULL DEFAULT 0,
    delivery_quantity BIGINT NOT NULL DEFAULT 0,
    delivery_to_traded DOUBLE,
    source_file VARCHAR NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, series, date)
);

CREATE TABLE IF NOT EXISTS equity_master (
    symbol VARCHAR PRIMARY KEY,
    name VARCHAR,
    isin VARCHAR,
    industry VARCHAR,
    series VARCHAR,
    listing_date DATE,
    delisting_date DATE,
    status VARCHAR,
    updated_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS ingest_log (
    product VARCHAR NOT NULL,
    date DATE NOT NULL,
    source_url VARCHAR,
    file_name VARCHAR,
    sha256 VARCHAR,
    num_rows BIGINT NOT NULL DEFAULT 0,
    status VARCHAR NOT NULL,
    error VARCHAR,
    duration_sec DOUBLE,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (product, date)
);

CREATE TABLE IF NOT EXISTS qc_issues (
    product VARCHAR NOT NULL,
    date DATE NOT NULL,
    symbol VARCHAR,
    series VARCHAR,
    code VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS data_gaps (
    product VARCHAR NOT NULL,
    date DATE NOT NULL,
    gap_type VARCHAR NOT NULL,
    detail VARCHAR,
    generated_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (product, date, gap_type)
);