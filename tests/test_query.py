from __future__ import annotations

from datetime import date

import pytest

from bhavkit.db import Database
from bhavkit.query import TEMPLATES, execute_template, run_sql


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.duckdb")
    d.bootstrap()
    for day in (date(2024, 1, 2), date(2024, 1, 3)):
        d.cr().execute(
            "INSERT OR REPLACE INTO bhav_daily (symbol, series, date, prev_close, "
            "close, total_traded_quantity, turnover, no_of_trades, delivery_qty, "
            "delivery_pct, source_file) VALUES ('ROCKET', 'EQ', ?, 100.0, ?, 5000, "
            "50000.0, 100, 1000, 80.0, ?)",
            [day, 100 + (day.day), "x.csv"],
        )
    yield d
    d.close()


def test_run_sql(db):
    df = run_sql(db, "SELECT count(*) AS n FROM bhav_daily")
    assert df["n"].to_list() == [2]


def test_run_sql_blocks_writes(db):
    with pytest.raises(ValueError, match="read-only"):
        run_sql(db, "CREATE TABLE tmp_bad (x INT)")


def test_top_gainers_template(db):
    df = execute_template(db, "top_gainers")
    assert df is not None
    assert df["symbol"].to_list() == ["ROCKET"]


def test_table_counts_template(db):
    counts = execute_template(db, "table_counts")
    assert counts is not None
    rows = dict(counts.iter_rows())
    assert rows["bhav_daily"] == 2
    assert rows["equity_master"] == 0


def test_unknown_template_returns_none(db):
    assert execute_template(db, "nope") is None


def test_templates_are_named():
    assert "latest" in TEMPLATES and "index_history" in TEMPLATES
    assert "top_gainers" in TEMPLATES and "delivery_ratio" in TEMPLATES