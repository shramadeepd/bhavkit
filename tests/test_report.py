from __future__ import annotations

from datetime import date

import pytest

from bhavkit.db import Database
from bhavkit.report import (
    build_report,
    db_range,
    detect_anomalies,
    detect_gaps,
    month_coverage,
    refresh_gaps_table,
    to_json,
    to_markdown,
)

DAY1, DAY2, DAY3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.duckdb")
    d.bootstrap()
    yield d
    d.close()


def _insert_bar(db, symbol, day, close, prev_close=100.0, volume=1000, trades=10):
    db.cr().execute(
        """
        INSERT OR REPLACE INTO bhav_daily
            (symbol, series, date, prev_close, open, high, low, last, close,
             avg_price, total_traded_quantity, turnover, no_of_trades,
             delivery_qty, delivery_pct, source_file)
        VALUES (?, 'EQ', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
        """,
        [symbol, day, prev_close, close, close, close, close, close, close,
         volume, close * volume, trades, "test.csv"],
    )


def _log(db, day, status):
    db.write_ingest_log(product="cm", date=day, status=status, num_rows=1)


def _seed(db):
    for day in (DAY1, DAY2, DAY3):
        _insert_bar(db, "SBIN", day, 100 + (DAY3 - day).days)
    _insert_bar(db, "ROCKET", DAY2, 300.0, prev_close=100.0)  # +200% move
    _insert_bar(db, "ZEROV", DAY1, 50.0, prev_close=50.0, volume=0, trades=5)
    _log(db, DAY1, "ingested")
    _log(db, DAY2, "ingested")
    _log(db, DAY3, "ingested")
    _log(db, date(2024, 1, 31), "not_a_trading_day")  # weekday not in advisory calendar
    _log(db, date(2024, 1, 5), "error")


def _master(db):
    db.cr().execute(
        "INSERT OR REPLACE INTO equity_master (symbol, name, series, status) VALUES "
        "('SBIN', 'State Bank', 'EQ', 'listed')"
    )


def test_db_range(db):
    _seed(db)
    lo, hi = db_range(db, "cm")
    assert lo == DAY1
    assert hi == date(2024, 1, 31)


def test_month_coverage(db):
    _seed(db)
    coverage = month_coverage(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    jan = coverage[0]
    assert jan.month == "2024-01"
    assert jan.expected == 21  # 23 weekdays - Jan 22 & Jan 26 advisory holidays
    assert jan.data_days == 3
    assert jan.holidays_detected == 1  # 2024-01-31
    assert jan.errors == 1
    assert jan.coverage_pct == pytest.approx(100 * 3 / 21, rel=1e-2)


def test_detect_gaps(db):
    _seed(db)
    gaps = detect_gaps(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    # Jan 1,2,3,4 logged as ingested; Jan 5 error; Jan 31 not-a-trading-day.
    # Jan 1 (Monday, real trading day) never logged -> missing.
    assert date(2024, 1, 2) not in gaps.missing_attempts
    assert date(2024, 1, 4) not in gaps.missing_attempts
    assert date(2024, 1, 1) in gaps.missing_attempts
    assert gaps.errors == [date(2024, 1, 5)]
    assert date(2024, 1, 31) in gaps.unknown_holidays
    assert date(2024, 1, 26) not in gaps.missing_attempts  # advisory holiday


def test_detect_anomalies(db):
    _seed(db)
    buckets = {b.code: b for b in detect_anomalies(db, date(2024, 1, 1), date(2024, 1, 31))}
    assert buckets["EXTREME_MOVE"].count == 1
    assert buckets["EXTREME_MOVE"].samples[0]["symbol"] == "ROCKET"
    assert buckets["ZERO_VOLUME_WITH_TRADES"].count == 1
    assert buckets["ZERO_VOLUME_WITH_TRADES"].samples[0]["symbol"] == "ZEROV"


def test_refresh_gaps_table(db):
    _seed(db)
    rep = build_report(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    n = refresh_gaps_table(db, rep)
    assert n > 0
    rows = db.query("SELECT DISTINCT gap_type FROM data_gaps ORDER BY 1")
    types = {r[0] for r in rows.iter_rows()}
    assert types == {"missing_attempt", "ingest_error", "unknown_holiday"}


def test_master_drift_in_report(db):
    _seed(db)
    _master(db)
    rep = build_report(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    assert "ROCKET" in rep.master_drift
    assert "SBIN" not in rep.master_drift


def test_markdown_and_json(db):
    _seed(db)
    _master(db)
    rep = build_report(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    md = to_markdown(rep)
    assert "# bhavkit data-quality report" in md
    assert "## Monthly coverage" in md
    assert "2024-01" in md
    assert "## Cross-dataset coverage" in md
    js = to_json(rep)
    assert '"product": "cm"' in js
    assert '"EXTREME_MOVE"' in js


def test_cross_tables(db):
    _seed(db)
    db.cr().execute(
        "INSERT INTO index_daily (index_name, date, close, source_file) VALUES "
        "('NIFTY 50', '2024-01-02', 21000.0, 'i.csv'), "
        "('NIFTY 50', '2024-01-03', 21100.0, 'i.csv')"
    )
    rep = build_report(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    ix = next(t for t in rep.cross_tables if t.table == "index_daily")
    assert ix.days == 2
    assert ix.rows == 2
    fo = next(t for t in rep.cross_tables if t.table == "fo_daily")
    assert fo.days == 0


def test_delivery_mismatch_bucket(db):
    _seed(db)
    db.cr().execute(
        "INSERT INTO deliverable_daily (symbol, series, date, quantity_traded, "
        "delivery_quantity, delivery_to_traded, source_file) VALUES "
        "('SBIN', 'EQ', '2024-01-02', 1000, 800, 80.0, 'd.csv')"
    )
    db.cr().execute(
        "INSERT OR REPLACE INTO bhav_daily (symbol, series, date, prev_close, open, "
        "high, low, last, close, avg_price, total_traded_quantity, turnover, "
        "no_of_trades, delivery_qty, delivery_pct, source_file) VALUES "
        "('SBIN', 'EQ', '2024-01-02', 100, 100, 100, 100, 100, 100, 100, "
        "1000, 100000, 10, 1000, 80.0, 'x.csv')"
    )
    rep = build_report(db, "cm", date(2024, 1, 1), date(2024, 1, 31))
    buckets = {b.code: b for b in rep.anomalies}
    assert buckets["DELIVERY_MISMATCH"].count == 1
    assert buckets["DELIVERY_MISMATCH"].samples[0]["symbol"] == "SBIN"