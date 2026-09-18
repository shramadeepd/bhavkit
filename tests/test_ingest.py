from __future__ import annotations

from datetime import date
from pathlib import Path

from bhavkit.config import Config
from bhavkit.db import Database
from bhavkit.ingest import update_product

DAY3 = date(2024, 1, 3)


def _local_config(tmp_path: Path) -> Config:
    return Config(
        source="local",
        local_dir=tmp_path / "mirror",
        data_dir=tmp_path / "data",
        db_path=tmp_path / "test.duckdb",
        concurrency=2,
    )


def test_end_to_end_download_and_ingest(tmp_path, local_mirror):
    mirror_root, write = local_mirror
    write(DAY3, _csv())

    cfg = _local_config(tmp_path)
    db = Database(cfg.db_path)
    db.bootstrap()
    summary = update_product(db, cfg, "cm", [DAY3])

    assert summary.ingested == 1
    assert summary.non_trading == 0
    assert summary.rows == 2
    assert db.fetchone("SELECT count(*) FROM bhav_daily")[0] == 2
    assert db.fetchone("SELECT status FROM ingest_log WHERE date=?", [DAY3])[0] == "ingested"
    db.close()


def test_rerun_is_skipped(tmp_path, local_mirror):
    _, write = local_mirror
    write(DAY3, _csv())

    cfg = _local_config(tmp_path)
    db = Database(cfg.db_path)
    db.bootstrap()
    first = update_product(db, cfg, "cm", [DAY3])
    second = update_product(db, cfg, "cm", [DAY3])

    assert first.ingested == 1
    assert second.ingested == 0
    assert second.skipped == 1
    db.close()


def test_force_reruns(tmp_path, local_mirror):
    _, write = local_mirror
    write(DAY3, _csv())

    cfg = _local_config(tmp_path)
    db = Database(cfg.db_path)
    db.bootstrap()
    first = update_product(db, cfg, "cm", [DAY3])
    third = update_product(db, cfg, "cm", [DAY3], force=True)

    assert third.ingested == 1
    assert first.rows == third.rows
    db.close()


def test_missing_file_flagged_non_trading(tmp_path):
    cfg = _local_config(tmp_path)
    db = Database(cfg.db_path)
    db.bootstrap()
    summary = update_product(db, cfg, "cm", [DAY3])

    assert summary.non_trading == 1
    assert summary.ingested == 0
    assert db.fetchone("SELECT status FROM ingest_log WHERE date=?", [DAY3])[0] == "not_a_trading_day"
    db.close()


def _csv() -> bytes:
    return (
        b"SYMBOL,SERIES,DATE,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
        b"CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
        b"SBIN,EQ,03-JAN-2024,620.00,626.00,635.50,621.10,631.00,632.00,628.50,4420123,278012.45,185432,1000000,84.32\n"
        b"TCS,EQ,03-JAN-2024,3800.00,3810.00,3860.00,3795.00,3850.00,3852.00,3830.00,1200000,920000.10,32111,850000,78.00\n"
    )