from __future__ import annotations

import io
import zipfile
from datetime import date

import polars as pl
import pytest

from bhavkit.clean import _normalize_columns, clean_bars, read_bhav_file


def _raw_df(csv: str) -> pl.DataFrame:
    return pl.read_csv(io.BytesIO(csv.encode()), infer_schema_length=0, try_parse_dates=False)


def test_parse_zip(sample_zip_path):
    df = read_bhav_file(sample_zip_path, inner_name="cm03JAN2024bhav.csv")
    assert df.height == 4
    assert df["SYMBOL"].to_list() == ["SBIN", "tcs", "RELIANCE", "INFY"]


def test_parse_plain_csv(tmp_path, sample_csv_content):
    path = tmp_path / "cm03JAN2024bhav.csv"
    path.write_text(sample_csv_content)
    df = read_bhav_file(path)
    assert df.height == 4


def test_parse_zip_missing_csv(tmp_path, sample_csv_bytes):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("README.txt", "nope")
    with pytest.raises(ValueError, match="no CSV found"):
        read_bhav_file(path)


def test_normalize_columns(sample_csv_content):
    df = _normalize_columns(_raw_df(sample_csv_content))
    assert set(df.columns) == {
        "symbol", "series", "date", "open", "high", "low", "close", "prev_close",
        "last", "avg_price", "total_traded_quantity", "turnover", "no_of_trades",
        "delivery_qty", "delivery_pct",
    }


def test_clean_bars_coerces_and_uppercases(sample_csv_content):
    bars, issues = clean_bars(_raw_df(sample_csv_content), expected_day=date(2024, 1, 3))
    assert issues == []
    assert bars.height == 4
    assert bars["symbol"].to_list() == ["SBIN", "TCS", "RELIANCE", "INFY"]
    assert bars["series"].to_list() == ["EQ", "EQ", "EQ", "BE"]
    assert bars["open"].dtype == pl.Float64
    assert bars["total_traded_quantity"].dtype == pl.Int64
    assert bars["date"].to_list() == [date(2024, 1, 3)] * 4


def test_clean_bars_dedupes(sample_csv_content):
    raw = _raw_df(sample_csv_content)
    dup = pl.concat([raw, raw])
    bars, issues = clean_bars(dup, expected_day=date(2024, 1, 3))
    assert bars.height == 4
    assert any(i["code"] == "DUPLICATE_ROWS" for i in issues)


def test_clean_bars_flags_bad_ohlc():
    csv = (
        "SYMBOL,SERIES,DATE,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
        "CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
        "BAD,EQ,03-JAN-2024,100,110,90,80,100,100,100,100,100,100,0,0\n"
        "GOOD,EQ,03-JAN-2024,100,100,110,80,105,105,100,100,100,100,0,0\n"
    )
    bars, issues = clean_bars(_raw_df(csv), expected_day=date(2024, 1, 3))
    assert bars.height == 2
    assert any(i["code"] == "OHLC_INVALID" and i["symbol"] == "BAD" for i in issues)


def test_clean_bars_drops_bad_date():
    csv = (
        "SYMBOL,SERIES,DATE,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
        "CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
        "X,EQ,not-a-date,100,100,110,80,100,100,100,1,1,1,0,0\n"
        "Y,EQ,03-JAN-2024,100,100,110,80,100,100,100,1,1,1,0,0\n"
    )
    bars, issues = clean_bars(_raw_df(csv), expected_day=date(2024, 1, 3))
    assert bars.height == 1
    assert bars["symbol"].to_list() == ["Y"]
    assert any(i["code"] == "BAD_DATE" for i in issues)


def test_clean_bars_new_isin_format():
    csv = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,"
        "TIMESTAMP,TOTALTRADES,ISIN,\n"
        "SBIN,EQ,626.00,635.50,621.10,632.00,631.00,620.00,4420123,278012450,"
        "03-JAN-2024,185432,INE002A01018,\n"
    )
    bars, issues = clean_bars(_raw_df(csv), expected_day=date(2024, 1, 3))
    assert issues == []
    assert bars.height == 1
    assert bars["symbol"][0] == "SBIN"
    assert bars["close"][0] == 632.0
    assert bars["date"][0] == date(2024, 1, 3)
    # new format has no delivery info -> defaults
    assert bars["delivery_qty"][0] == 0
    assert bars["avg_price"][0] is None
    # TOTTRDVAL is already in rupees
    assert bars["turnover"][0] == 278012450.0


def test_clean_bars_turnover_lacs_scaled_to_rupees(sample_csv_content):
    bars, _ = clean_bars(_raw_df(sample_csv_content), expected_day=date(2024, 1, 3))
    row = bars.filter(pl.col("symbol") == "SBIN")
    assert row["turnover"][0] == pytest.approx(278012.45 * 100000)


def test_clean_bars_missing_required_column_raises():
    raw = pl.DataFrame({"symbol": ["A"], "series": ["EQ"]})
    with pytest.raises(ValueError, match="missing required columns"):
        clean_bars(raw)