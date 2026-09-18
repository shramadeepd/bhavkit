from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from bhavkit.clean import clean_deliverable, clean_fo, clean_index
from bhavkit.config import Config
from bhavkit.db import Database
from bhavkit.ingest import update_product

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "src" / "bhavkit" / "schema.sql"

DAY = date(2024, 1, 3)

IDX_CSV = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
    "Nifty 50,03-01-2024,21661.1,21677,21500.35,21517.35,-148.45,-.69,311933117,32329.23,22.94,3.77,1.29\n"
    "Nifty Next 50,03-01-2024,53408.35,53842.1,53225.2,53680.35,402.85,.76,382533455,16489.75,25.81,4.31,1.38\n"
)

FO_CSV = (
    "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,"
    "CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
    "FUTIDX,BANKNIFTY,25-Jan-2024,0,XX,47849.85,48086.85,47763.75,47931.95,47931.95,172345,1239038.88,1998315,-285300,03-JAN-2024,\n"
    "OPTIDX,NIFTY,25-Jan-2024,21700,CE,0,0,0,300.5,300.5,4000,120.5,500000,1000,03-JAN-2024,\n"
    "FUTSTK,RELIANCE,25-Jan-2024,0,,2600,2650,2595,2640,2640,1000,2640.0,50000,0,03-JAN-2024,\n"
)

DELIV_CSV = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
    "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    "20MICRONS, EQ, 03-Jan-2024, 171.00, 171.15, 180.80, 169.50, 180.00, 179.25, 176.59, "
    "261772, 462.26, 12623, 115742, 44.21\n"
    "21STCENMGM, BE, 03-Jan-2024, 31.65, 31.05, 31.05, 31.05, 31.05, 31.05, 31.05, "
    "2719, 0.84, 33, -, -\n"
    "IREDA, EQ, 03-Jan-2024, 100.0, 100.0, 105.0, 99.0, 104.0, 104.0, 101.0, "
    "24148229, 25000.0, 100000, 9924644, 41.10\n"
    "IREDA, N1, 03-Jan-2024, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "
    "2, 0.0, 1, 2, 100.00\n"
)


def _raw(csv: str) -> pl.DataFrame:
    return pl.read_csv(io.BytesIO(csv.encode()), infer_schema_length=0, try_parse_dates=False)


def test_clean_index():
    idx, issues = clean_index(_raw(IDX_CSV), expected_day=DAY)
    assert issues == []
    assert idx.height == 2
    assert idx["index_name"].to_list() == ["NIFTY 50", "NIFTY NEXT 50"]
    assert idx["date"].to_list() == [DAY] * 2
    assert idx["close"].to_list() == [21517.35, 53680.35]
    assert idx["volume"].dtype == pl.Int64
    assert all(t == pl.Float64 for t in idx["open", "high", "low", "close"].dtypes)


def test_clean_index_flags_bad_ohlc():
    bad = IDX_CSV.replace("21661.1,21677", "21661.1,21500.35")  # high < close
    idx, issues = clean_index(_raw(bad), expected_day=DAY)
    assert idx.height == 2
    assert any(i["code"] == "OHLC_INVALID" for i in issues)


def test_clean_fo():
    fo, issues = clean_fo(_raw(FO_CSV), expected_day=DAY)
    assert fo.height == 3
    assert issues == []
    fut = fo.filter(pl.col("instrument") == "FUTIDX")
    opt = fo.filter(pl.col("option_type") == "CE")
    rel = fo.filter(pl.col("symbol") == "RELIANCE")
    # blank OPTION_TYP on futures -> "XX"
    assert rel["option_type"].to_list() == ["XX"]
    # VAL_INLAKH is in lakhs -> rupees
    assert fut["value"].to_list()[0] == pytest.approx(1239038.88 * 100000)
    assert fut["expiry_date"].to_list()[0] == date(2024, 1, 25)
    # zero OHLC is legal in FO (illiquid strikes)
    assert opt["open"].to_list()[0] == 0.0
    assert opt["close"].to_list()[0] == 300.5
    assert fo["date"].to_list() == [DAY] * 3


def test_clean_fo_dedupes_full_pk():
    fo, issues = clean_fo(pl.concat([_raw(FO_CSV), _raw(FO_CSV)]), expected_day=DAY)
    assert fo.height == 3
    assert any(i["code"] == "DUPLICATE_ROWS" for i in issues)


def test_clean_deliverable():
    dv, issues = clean_deliverable(_raw(DELIV_CSV), expected_day=DAY)
    assert dv.height == 4  # EQ + N1 rows for IREDA both kept
    assert issues == []
    eq = dv.filter(pl.col("series") == "EQ")
    n1 = dv.filter(pl.col("series") == "N1")
    assert eq.height == 2
    assert eq.filter(pl.col("symbol") == "IREDA")["delivery_quantity"].to_list()[0] == 9924644
    assert eq.filter(pl.col("symbol") == "20MICRONS")["delivery_to_traded"].to_list()[0] == 44.21
    # '-' values -> 0 / null (21STCENMGM is series BE, not EQ)
    zero = dv.filter(pl.col("symbol") == "21STCENMGM")
    assert zero["delivery_quantity"].to_list()[0] == 0
    assert zero["delivery_to_traded"].to_list()[0] is None
    assert n1["quantity_traded"].to_list()[0] == 2


def _fo_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("fo03JAN2024bhav.csv", FO_CSV)
    return buf.getvalue()


def _ingest_all(tmp_path, mirror_root) -> tuple[Database, Config]:
    (mirror_root / "idx" / "2024" / "JAN").mkdir(parents=True, exist_ok=True)
    (mirror_root / "fo" / "2024" / "JAN").mkdir(parents=True, exist_ok=True)
    (mirror_root / "deliv" / "2024" / "JAN").mkdir(parents=True, exist_ok=True)
    (mirror_root / "idx" / "2024" / "JAN" / "ind_close_all_03012024.csv").write_text(IDX_CSV)
    (mirror_root / "fo" / "2024" / "JAN" / "fo03JAN2024bhav.csv.zip").write_bytes(_fo_zip_bytes())
    (mirror_root / "deliv" / "2024" / "JAN" / "sec_bhavdata_full_03012024.csv").write_text(DELIV_CSV)
    cfg = Config(source="local", local_dir=mirror_root, data_dir=tmp_path / "data",
                 db_path=tmp_path / "test.duckdb", concurrency=2)
    db = Database(cfg.db_path)
    db.bootstrap()
    return db, cfg


def test_ingest_idx_fo_deliv(tmp_path):
    db, cfg = _ingest_all(tmp_path, tmp_path / "mirror")
    for product in ("idx", "fo", "deliv"):
        summary = update_product(db, cfg, product, [DAY])
        assert summary.ingested == 1
        assert summary.errors == 0
    assert db.fetchone("SELECT count(*) FROM index_daily")[0] == 2
    assert db.fetchone("SELECT count(*) FROM fo_daily")[0] == 3
    assert db.fetchone("SELECT count(*) FROM deliverable_daily")[0] == 4
    db.close()


def test_sources_resolve_all_products(tmp_path):
    from bhavkit.sources.local import LocalSource
    from bhavkit.sources.nse import NSESource

    nse = NSESource("https://nsearchives.nseindia.com")
    assert nse.resolve("cm", DAY).url.endswith("cm03JAN2024bhav.csv.zip")
    assert nse.resolve("idx", DAY).url.endswith("ind_close_all_03012024.csv")
    assert nse.resolve("fo", DAY).url.endswith("fo03JAN2024bhav.csv.zip")
    assert nse.resolve("deliv", DAY).url.endswith("sec_bhavdata_full_03012024.csv")

    mirror = tmp_path / "mirror"
    fo_dir = mirror / "fo" / "2024" / "JAN"
    fo_dir.mkdir(parents=True, exist_ok=True)
    (fo_dir / "fo03JAN2024bhav.csv.zip").write_bytes(_fo_zip_bytes())
    local = LocalSource(mirror)
    resolved = local.resolve("fo", DAY)
    assert resolved is not None and resolved.url.endswith(".csv.zip")
    assert nse.resolve("fo", DAY).inner_name == "fo03JAN2024bhav.csv"


def test_migration_v1_deliverable_rebuilt(tmp_path: Path):
    """Opening a v1 DB (deliverable PK symbol,date) migrates to v2 preserving rows."""
    import duckdb

    path = tmp_path / "legacy.duckdb"
    con = duckdb.connect(str(path))
    con.execute(SCHEMA_SQL.read_text().replace(
        "PRIMARY KEY (symbol, series, date)", "PRIMARY KEY (symbol, date)"
    ))
    con.execute(
        "INSERT INTO schema_migrations (version) VALUES (1)"
    )
    con.execute(
        "INSERT INTO deliverable_daily (symbol, series, date, quantity_traded, "
        "delivery_quantity, delivery_to_traded, source_file) VALUES "
        "('SBIN', 'EQ', '2024-01-03', 100, 80, 80.0, 'old.csv')"
    )
    con.close()

    db = Database(path)
    db.bootstrap()
    assert db.schema_version == 2
    row = db.fetchone(
        "SELECT series, delivery_quantity FROM deliverable_daily WHERE symbol='SBIN'"
    )
    assert row == ("EQ", 80)
    pk = db.cr().execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name='deliverable_daily' AND constraint_type='PRIMARY KEY'"
    ).fetchone()[0]
    assert pk == ["symbol", "series", "date"]
    db.close()