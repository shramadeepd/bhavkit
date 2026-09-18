from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from bhavkit.config import Config
from bhavkit.db import Database
from bhavkit.metadata import refresh_equity_master

MASTER_CSV = (
    "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
    "SBIN,State Bank of India,EQ,01-JAN-1994,INE062A01020\n"
    "TCS,Tata Consultancy Services,EQ,25-AUG-2004,INE467B01029\n"
    "ALPHA,Alpha Ltd,BE,15-MAR-2010,INE000000001\n"
    "+NIFTY,Index Fund,NIFTY,10-JAN-2020,INE000000002\n"
)


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.duckdb")
    d.bootstrap()
    yield d
    d.close()


def _cfg(tmp_path) -> Config:
    return Config(data_dir=tmp_path / "data", db_path=tmp_path / "test.duckdb",
                  source="local", local_dir=tmp_path / "mirror")


def test_refresh_master_from_file(tmp_path, db):
    csv = tmp_path / "EQUITY_L.csv"
    csv.write_text(MASTER_CSV)
    summary = refresh_equity_master(db, _cfg(tmp_path), local_file=csv)
    assert summary["rows"] == 4
    rows = db.query("SELECT symbol, name, series, listing_date, status FROM equity_master "
                    "ORDER BY symbol")
    assert rows.height == 4
    assert rows["symbol"].to_list() == ["+NIFTY", "ALPHA", "SBIN", "TCS"]
    assert rows["series"].to_list() == ["NIFTY", "BE", "EQ", "EQ"]
    tcs = rows.filter(pl.col("symbol") == "TCS")
    assert tcs["listing_date"][0] == date(2004, 8, 25)
    master_log = db.fetchone(
        "SELECT status, num_rows FROM ingest_log WHERE product='master'"
    )
    assert master_log == ("ingested", 4)


def test_refresh_master_drift(tmp_path, db):
    db.cr().execute(
        "INSERT INTO bhav_daily (symbol, series, date, source_file) VALUES "
        "('SBIN', 'EQ', '2024-01-02', 'x.csv'), "
        "('GHOST', 'EQ', '2024-01-02', 'x.csv'), "
        "('OTHER', 'BE', '2024-01-02', 'x.csv')"
    )
    csv = tmp_path / "EQUITY_L.csv"
    csv.write_text(MASTER_CSV)
    summary = refresh_equity_master(db, _cfg(tmp_path), local_file=csv)
    assert "GHOST" in summary["drift"]
    assert "SBIN" not in summary["drift"]
    assert "OTHER" not in summary["drift"]  # BE series ignored for drift
    assert summary["drift_count"] == 1


def test_refresh_master_prefers_eq_series(tmp_path, db):
    csv = tmp_path / "EQUITY_L.csv"
    csv.write_text(
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
        "DUP,Old Series,BE,01-JAN-2020,INE000000001\n"
        "DUP,New Series,EQ,01-JAN-2020,INE000000002\n"
    )
    refresh_equity_master(db, _cfg(tmp_path), local_file=csv)
    row = db.fetchone("SELECT series, isin FROM equity_master WHERE symbol='DUP'")
    assert row == ("EQ", "INE000000002")


def test_refresh_master_empty_file_raises(tmp_path, db):
    csv = tmp_path / "EQUITY_L.csv"
    csv.write_text("")
    with pytest.raises(ValueError, match="failed to read"):
        refresh_equity_master(db, _cfg(tmp_path), local_file=csv)