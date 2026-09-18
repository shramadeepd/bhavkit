from __future__ import annotations

from datetime import date

import pytest

from bhavkit.db import Database
from bhavkit.export import export_table


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.duckdb")
    d.bootstrap()
    for day in (date(2024, 1, 2), date(2024, 1, 3)):
        d.cr().execute(
            "INSERT OR REPLACE INTO bhav_daily (symbol, series, date, close, "
            "total_traded_quantity, turnover, no_of_trades, delivery_qty, "
            "delivery_pct, source_file) VALUES (?, 'EQ', ?, ?, 1000, 100.0, 10, 0, 0, ?)",
            ["SBIN", day, 600 + day.day, "x.csv"],
        )
        d.cr().execute(
            "INSERT OR REPLACE INTO bhav_daily (symbol, series, date, close, "
            "total_traded_quantity, turnover, no_of_trades, delivery_qty, "
            "delivery_pct, source_file) VALUES (?, 'BE', ?, ?, 100, 10.0, 3, 0, 0, ?)",
            ["TATAMOTORS", day, 800 + day.day, "x.csv"],
        )
    yield d
    d.close()


def test_export_parquet(db, tmp_path):
    out = tmp_path / "exports"
    target = export_table(db, "bhav_daily", start=date(2024, 1, 3), end=date(2024, 1, 3),
                          symbols=["SBIN"], fmt="parquet", out=out)
    assert target.suffix == ".parquet"
    assert target.is_file()
    assert db.cr().execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0] == 1


def test_export_csv_list(db, tmp_path):
    target = export_table(db, "bhav_daily", symbols=["SBIN", "TATAMOTORS"],
                          series="EQ", fmt="csv",
                          out=tmp_path / "one.csv")
    assert target.suffix == ".csv"
    lines = target.read_text().strip().splitlines()
    assert len(lines) == 1 + 2  # header + 2 rows (one EQ row per day)
    assert "SBIN" in lines[1]


def test_export_equity_master_no_date(db, tmp_path):
    db.cr().execute(
        "INSERT INTO equity_master (symbol, name, status) VALUES ('SBIN', 'SBI', 'listed')"
    )
    target = export_table(db, "equity_master", fmt="parquet", out=tmp_path / "m.parquet")
    assert db.cr().execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0] == 1


def test_export_unknown_table(db, tmp_path):
    with pytest.raises(ValueError, match="unknown export table"):
        export_table(db, "nope", out=tmp_path / "x.parquet")


def test_export_bad_format(db, tmp_path):
    with pytest.raises(ValueError, match="format must be"):
        export_table(db, "bhav_daily", fmt="json", out=tmp_path / "x.json")