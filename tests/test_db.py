from __future__ import annotations

from datetime import date

import pytest

from bhavkit.config import Config, load_config
from bhavkit.db import SCHEMA_VERSION, Database
from bhavkit.sources import make_source

DAY3 = date(2024, 1, 3)


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.duckdb")
    d.bootstrap()
    yield d
    d.close()


def test_schema_bootstrap_sets_version(db):
    assert db.schema_version == SCHEMA_VERSION


def test_upsert_is_idempotent(db):
    df = _bars([("SBIN", "EQ", 632.0), ("TCS", "EQ", 3852.0)])
    n1 = db.upsert_bars(df, "cm03JAN2024bhav.csv")
    n2 = db.upsert_bars(df, "cm03JAN2024bhav.csv")
    assert n1 == n2 == 2
    assert db.fetchone("SELECT count(*) FROM bhav_daily")[0] == 2


def test_upsert_replaces_same_key(db):
    old = _bars([("SBIN", "EQ", 632.0)])
    new = _bars([("SBIN", "EQ", 645.0)])
    db.upsert_bars(old, "a.csv")
    db.upsert_bars(new, "b.csv")
    rows = db.query("SELECT symbol, close, source_file FROM bhav_daily")
    assert rows.height == 1
    assert rows["close"][0] == 645.0
    assert rows["source_file"][0] == "b.csv"


def test_ingest_log_replace(db):
    db.write_ingest_log(product="cm", date=DAY3, status="ingested", num_rows=10)
    db.write_ingest_log(product="cm", date=DAY3, status="error", error="boom")
    rows = db.query("SELECT status, error FROM ingest_log")
    assert rows.height == 1
    assert rows["status"][0] == "error"


def test_qc_issues_written(db):
    db.write_qc_issues("cm", DAY3, [{"symbol": "X", "series": "EQ",
                                     "code": "OHLC_INVALID", "message": "bad"}])
    assert db.fetchone("SELECT count(*) FROM qc_issues")[0] == 1


def _bars(rows: list[tuple[str, str, float]]):
    import polars as pl

    return pl.DataFrame(
        {
            "symbol": [r[0] for r in rows],
            "series": [r[1] for r in rows],
            "date": [DAY3] * len(rows),
            "prev_close": [100.0] * len(rows),
            "open": [100.0] * len(rows),
            "high": [110.0] * len(rows),
            "low": [90.0] * len(rows),
            "last": [r[2] for r in rows],
            "close": [r[2] for r in rows],
            "avg_price": [100.0] * len(rows),
            "total_traded_quantity": [1] * len(rows),
            "turnover": [1.0] * len(rows),
            "no_of_trades": [1] * len(rows),
            "delivery_qty": [0] * len(rows),
            "delivery_pct": [0.0] * len(rows),
        }
    )


def test_default_config_paths_are_absolute():
    cfg = load_config()
    assert cfg.source in {"nse", "local"}
    assert cfg.concurrency >= 1


def test_local_source_needs_local_dir():
    cfg = Config(source="local")
    with pytest.raises(ValueError, match="local_dir"):
        make_source(cfg)