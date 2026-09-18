"""Parsing + cleaning of NSE bhavcopy files with Polars.

Reads raw CSVs (possibly inside a zip) as all-string frames, then renames /
coerces / validates into canonical table shapes for `bhav_daily`, `index_daily`,
`fo_daily`, and `deliverable_daily`.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

# Raw bhavcopy headers -> canonical column. NSE changed formats: the classic
# file carried DELIV_* columns and TURNOVER_LACS; the current format has ISIN
# and TIMESTAMP. Both are normalized to the same canonical shape below.
COLUMN_MAP = {
    # classic / modern (DELIV) format
    "SYMBOL": "symbol",
    "SERIES": "series",
    "DATE": "date",
    "PREV_CLOSE": "prev_close",
    "OPEN_PRICE": "open",
    "HIGH_PRICE": "high",
    "LOW_PRICE": "low",
    "LAST_PRICE": "last",
    "CLOSE_PRICE": "close",
    "AVG_PRICE": "avg_price",
    "TTL_TRD_QNTY": "total_traded_quantity",
    "TURNOVER_LACS": "turnover",
    "NO_OF_TRADES": "no_of_trades",
    "DELIV_QTY": "delivery_qty",
    "DELIV_PER": "delivery_pct",
    # current ISIN format
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "LAST": "last",
    "PREVCLOSE": "prev_close",
    "TOTTRDQTY": "total_traded_quantity",
    "TOTTRDVAL": "turnover",
    "TIMESTAMP": "date",
    "TOTALTRADES": "no_of_trades",
}

PRICE_COLUMNS = ("open", "high", "low", "close", "prev_close", "last", "avg_price", "turnover")
INT_COLUMNS = ("total_traded_quantity", "no_of_trades", "delivery_qty")
FLOAT_OPTIONAL = ("delivery_pct",)
REQUIRED = ("symbol", "series", "date", "open", "high", "low", "close")
CANONICAL = (
    "symbol", "series", "date", "open", "high", "low", "close", "prev_close",
    "last", "avg_price", "turnover", "total_traded_quantity", "no_of_trades",
    "delivery_qty", "delivery_pct",
)

DATE_FMT = "%d-%b-%Y"

# --- index_daily (ind_close_all_DDMMYYYY.csv) ---
INDEX_MAP = {
    "INDEX NAME": "index_name",
    "INDEX DATE": "date",
    "OPEN INDEX VALUE": "open",
    "HIGH INDEX VALUE": "high",
    "LOW INDEX VALUE": "low",
    "CLOSING INDEX VALUE": "close",
    "VOLUME": "volume",
    "TURNOVER (RS. CR.)": "turnover",
}
INDEX_REQUIRED = ("index_name", "date", "open", "high", "low", "close")
INDEX_CANONICAL = ("index_name", "date", "open", "high", "low", "close", "volume", "turnover")

# --- fo_daily (foDDMONYYYYbhav.csv inside a zip) ---
FO_MAP = {
    "INSTRUMENT": "instrument",
    "SYMBOL": "symbol",
    "EXPIRY_DT": "expiry_date",
    "OPTION_TYP": "option_type",
    "STRIKE_PR": "strike_price",
    "STRIKE_PRC": "strike_price",
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "SETTLE_PR": "settle_price",
    "CONTRACTS": "contracts",
    "VAL_INLAKH": "value",
    "OPEN_INT": "open_interest",
    "CHG_IN_OI": "change_in_oi",
    "TIMESTAMP": "date",
}
FO_REQUIRED = ("instrument", "symbol", "open", "high", "low", "close")
FO_CANONICAL = (
    "instrument", "symbol", "expiry_date", "option_type", "strike_price", "date",
    "open", "high", "low", "close", "settle_price", "contracts", "value",
    "open_interest", "change_in_oi",
)
FO_PK = ("instrument", "symbol", "expiry_date", "option_type", "strike_price", "date")

# --- deliverable_daily (sec_bhavdata_full_DDMMYYYY.csv) ---
DELIV_MAP = {
    "SYMBOL": "symbol",
    "SERIES": "series",
    "DATE1": "date",
    "TTL_TRD_QNTY": "quantity_traded",
    "DELIV_QTY": "delivery_quantity",
    "DELIV_PER": "delivery_to_traded",
}
DELIV_REQUIRED = ("symbol", "date")
DELIV_CANONICAL = (
    "symbol", "date", "series", "isin", "quantity_traded", "delivery_quantity",
    "delivery_to_traded",
)


def read_bhav_file(path: Path, inner_name: str | None = None) -> pl.DataFrame:
    """Read a bhavcopy zip (or plain CSV) into an all-string dataframe."""
    if path.suffix.lower() == ".zip":
        body = _extract_csv_from_zip(path, inner_name)
    else:
        body = path.read_bytes()
    if not body.strip():
        raise ValueError(f"file is empty: {path}")
    df = pl.read_csv(io.BytesIO(body), infer_schema_length=0, try_parse_dates=False)
    if df.is_empty():
        raise ValueError(f"no rows parsed from {path}")
    return df


def _extract_csv_from_zip(path: Path, inner_name: str | None) -> bytes:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if inner_name:
            match = next((n for n in names if n.lower() == inner_name.lower()), None)
        else:
            match = next((n for n in names if n.lower().endswith(".csv")), None)
        if match is None:
            raise ValueError(f"no CSV found in {path.name} (has: {names[:5]})")
        if zf.getinfo(match).is_dir():
            raise ValueError(f"{path.name}: {match} is a directory entry")
        return zf.read(match)


def _rename_keep(
    df: pl.DataFrame, mapping: dict[str, str], canonical: tuple[str, ...]
) -> pl.DataFrame:
    """Rename known raw headers to canonical names; keep only canonical columns."""
    rename: dict[str, str] = {}
    for col in df.columns:
        key = col.strip().upper()
        if key in mapping:
            rename[col] = mapping[key]
    df = df.rename(rename)
    return df.select([c for c in canonical if c in df.columns])


def _normalize_columns(df: pl.DataFrame) -> pl.DataFrame:
    return _rename_keep(df, COLUMN_MAP, CANONICAL)


def _lift_string_col(out: pl.DataFrame, col: str, to_float: bool = True) -> pl.DataFrame:
    """Strip + cast a string column (float or int); non-numeric -> null."""
    dtype = pl.Float64 if to_float else pl.Int64
    return out.with_columns(
        pl.col(col).str.strip_chars().cast(dtype, strict=False)
        if col in out.columns
        else pl.lit(None, dtype=dtype).alias(col)
    )


def _fill_defaults(out: pl.DataFrame) -> pl.DataFrame:
    """Ensure every canonical column exists so downstream select keeps working."""
    for col in CANONICAL:
        if col in out.columns:
            continue
        if col in INT_COLUMNS or col in FLOAT_OPTIONAL:
            out = out.with_columns(pl.lit(0, dtype=pl.Int64).alias(col)) if col in INT_COLUMNS \
                else out.with_columns(pl.lit(0.0).alias(col))
        elif col in PRICE_COLUMNS:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    return out


def clean_bars(
    df: pl.DataFrame, expected_day: date | None = None
) -> tuple[pl.DataFrame, list[dict]]:
    """Coerce, validate, dedupe. Returns (bars, qc issues)."""

    def _upper(col: str) -> str:
        return col.strip().upper()

    raw_has_turnover_lacs = any(_upper(c) == "TURNOVER_LACS" for c in df.columns)
    issues: list[dict] = []
    raw = _normalize_columns(df)

    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"file missing required columns: {missing} (got {raw.columns})")

    out = raw.with_columns(
        pl.col("symbol").str.strip_chars().str.to_uppercase(),
        pl.col("series").str.strip_chars().str.to_uppercase(),
    )

    for col in PRICE_COLUMNS:
        if col in out.columns:
            out = out.with_columns(pl.col(col).str.strip_chars().cast(pl.Float64, strict=False))
    for col in INT_COLUMNS:
        if col in out.columns:
            out = out.with_columns(
                pl.col(col).str.strip_chars().cast(pl.Int64, strict=False).fill_null(0)
            )
    for col in FLOAT_OPTIONAL:
        if col in out.columns:
            out = out.with_columns(pl.col(col).str.strip_chars().cast(pl.Float64, strict=False))

    out = _fill_defaults(out)

    if raw_has_turnover_lacs:
        # Classic format reports turnover in lakhs -> normalize to rupees.
        out = out.with_columns((pl.col("turnover") * 100000).alias("turnover"))

    out = out.with_columns(
        pl.col("date")
        .str.strip_chars()
        .str.strptime(pl.Date, DATE_FMT, strict=False)
    )

    bad_date = out.filter(pl.col("date").is_null())
    if bad_date.height:
        issues += [
            {"symbol": s, "series": ser, "code": "BAD_DATE", "message": f"unparsable date {d!r}"}
            for s, ser, d in zip(
                bad_date["symbol"], bad_date["series"], bad_date["date"], strict=False
            )
        ]

    out = out.filter(pl.col("date").is_not_null())

    empty_symbol = out.filter(pl.col("symbol").str.len_chars() == 0)
    if empty_symbol.height:
        issues += [{"symbol": None, "series": None, "code": "EMPTY_SYMBOL",
                    "message": "empty symbol row"}]
    out = out.filter(pl.col("symbol").str.len_chars() > 0)

    if expected_day is not None:
        wrong_day = out.filter(pl.col("date") != pl.lit(expected_day))
        for sym, ser, d in wrong_day.select(["symbol", "series", "date"]).iter_rows():
            issues.append({"symbol": sym, "series": ser, "code": "DATE_MISMATCH",
                           "message": f"file date {expected_day} but row date {d}"})

    _flag_ohlc(out, issues)

    before = out.height
    out = out.unique(subset=["symbol", "series", "date"], keep="first", maintain_order=True)
    if out.height < before:
        issues.append({"symbol": None, "series": None, "code": "DUPLICATE_ROWS",
                       "message": f"dropped {before - out.height} duplicate rows"})

    return out, issues


def clean_index(
    df: pl.DataFrame, expected_day: date | None = None
) -> tuple[pl.DataFrame, list[dict]]:
    """Coerce the index closing file into `index_daily` shape."""
    issues: list[dict] = []
    raw = _rename_keep(
        df, INDEX_MAP,
        ("index_name", "date", "open", "high", "low", "close", "volume", "turnover"),
    )
    missing = [c for c in INDEX_REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"file missing required columns: {missing} (got {raw.columns})")

    out = raw.with_columns(
        pl.col("index_name").str.strip_chars().str.to_uppercase(),
    )
    for col in ("open", "high", "low", "close"):
        out = _lift_string_col(out, col, to_float=True)
    out = _lift_string_col(out, "turnover", to_float=True).with_columns(
        pl.col("turnover").fill_null(0.0)
    )
    out = _lift_string_col(out, "volume", to_float=False).with_columns(
        pl.col("volume").fill_null(0).cast(pl.Int64)
    )

    out = out.with_columns(
        pl.col("date").str.strip_chars().str.strptime(pl.Date, "%d-%m-%Y", strict=False)
    )
    bad_date = out.filter(pl.col("date").is_null())
    if bad_date.height:
        issues += [
            {"symbol": name, "series": None, "code": "BAD_DATE",
             "message": f"unparsable date {d!r}"}
            for name, d in zip(bad_date["index_name"], bad_date["date"], strict=False)
        ]
    out = out.filter(pl.col("date").is_not_null())

    empty = out.filter(pl.col("index_name").str.len_chars() == 0)
    if empty.height:
        issues += [{"symbol": None, "series": None, "code": "EMPTY_SYMBOL",
                    "message": "empty index name"}]
    out = out.filter(pl.col("index_name").str.len_chars() > 0)

    if expected_day is not None:
        wrong = out.filter(pl.col("date") != pl.lit(expected_day))
        for name, d in wrong.select(["index_name", "date"]).iter_rows():
            issues.append({"symbol": name, "series": None, "code": "DATE_MISMATCH",
                           "message": f"file date {expected_day} but row date {d}"})

    _flag_ohlc(out, issues, ident="index_name")

    before = out.height
    out = out.unique(subset=["index_name", "date"], keep="first", maintain_order=True)
    if out.height < before:
        issues.append({"symbol": None, "series": None, "code": "DUPLICATE_ROWS",
                       "message": f"dropped {before - out.height} duplicate index rows"})
    return out, issues


def clean_fo(df: pl.DataFrame, expected_day: date | None = None) -> tuple[pl.DataFrame, list[dict]]:
    """Coerce the F&O bhavcopy into `fo_daily` shape."""
    issues: list[dict] = []
    raw_has_val_inlakh = any(c.strip().upper() == "VAL_INLAKH" for c in df.columns)
    raw = _rename_keep(df, FO_MAP, (
        "instrument", "symbol", "expiry_date", "option_type", "strike_price", "date",
        "open", "high", "low", "close", "settle_price", "contracts", "value",
        "open_interest", "change_in_oi",
    ))
    missing = [c for c in FO_REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"file missing required columns: {missing} (got {raw.columns})")

    out = raw.with_columns(
        pl.col("instrument").str.strip_chars().str.to_uppercase(),
        pl.col("symbol").str.strip_chars().str.to_uppercase(),
    )
    for col in ("open", "high", "low", "close", "settle_price", "strike_price"):
        out = _lift_string_col(out, col, to_float=True)
    if "strike_price" not in out.columns:
        out = out.with_columns(pl.lit(0.0).alias("strike_price"))
    else:
        out = out.with_columns(pl.col("strike_price").fill_null(0.0))
    for col in ("contracts", "open_interest", "change_in_oi"):
        if col in out.columns:
            out = _lift_string_col(out, col, to_float=False)
        else:
            out = out.with_columns(pl.lit(0, dtype=pl.Int64).alias(col))
        out = out.with_columns(pl.col(col).fill_null(0).cast(pl.Int64))
    out = _lift_string_col(out, "value", to_float=True).with_columns(
        pl.col("value").fill_null(0.0)
    )
    if raw_has_val_inlakh:
        # VAL_INLAKH is in lakhs -> normalize to rupees.
        out = out.with_columns((pl.col("value") * 100000).alias("value"))

    out = out.with_columns(
        _string_or_lit(out, "expiry_date")
        .str.strip_chars()
        .str.strptime(pl.Date, DATE_FMT, strict=False)
        .alias("expiry_date")
    )
    out = out.with_columns(
        _string_or_lit_upper(out, "option_type").alias("option_type")
    )

    if "date" in out.columns:
        out = out.with_columns(
            pl.col("date").str.strip_chars().str.strptime(pl.Date, DATE_FMT, strict=False)
        )
        if expected_day is not None:
            wrong = out.filter(
                pl.col("date").is_not_null() & (pl.col("date") != pl.lit(expected_day))
            )
            for row in wrong.select(["instrument", "symbol", "date"]).iter_rows():
                issues.append({"symbol": row[1], "series": None, "code": "DATE_MISMATCH",
                               "message": f"file date {expected_day} but row date {row[2]}"})
        out = out.with_columns(pl.col("date").fill_null(pl.lit(expected_day)))
    else:
        if expected_day is None:
            raise ValueError("FO file has no TIMESTAMP and no expected day provided")
        out = out.with_columns(pl.lit(expected_day, dtype=pl.Date).alias("date"))

    bad_date = out.filter(pl.col("date").is_null())
    if bad_date.height:
        issues.append({"symbol": None, "series": None, "code": "BAD_DATE",
                       "message": f"{bad_date.height} rows with unresolvable date"})
        out = out.filter(pl.col("date").is_not_null())

    no_expiry = out.filter(pl.col("expiry_date").is_null())
    if no_expiry.height:
        issues += [
            {"symbol": s, "series": None, "code": "EXPIRY_MISSING",
             "message": f"row without expiry: instrument={i}"}
            for i, s in no_expiry.select(["instrument", "symbol"]).iter_rows()
        ]
        out = out.filter(pl.col("expiry_date").is_not_null())

    out = out.with_columns(
        pl.col("option_type").fill_null("XX").str.strip_chars().str.to_uppercase()
    )
    out = out.with_columns(
        pl.when(pl.col("option_type") == "")
        .then(pl.lit("XX"))
        .otherwise(pl.col("option_type"))
        .alias("option_type")
    )
    empty_sym = out.filter(pl.col("symbol").str.len_chars() == 0)
    if empty_sym.height:
        issues.append({"symbol": None, "series": None, "code": "EMPTY_SYMBOL",
                       "message": "empty symbol row"})
    out = out.filter(pl.col("symbol").str.len_chars() > 0)

    # Note: no OHLC bounds check here — zeros in OHLC are legitimate in the
    # F&O file (illiquid strikes carry open/high/low = 0 but valid close/settle).

    before = out.height
    out = out.unique(subset=list(FO_PK), keep="first", maintain_order=True)
    if out.height < before:
        issues.append({"symbol": None, "series": None, "code": "DUPLICATE_ROWS",
                       "message": f"dropped {before - out.height} duplicate FO rows"})
    return out, issues


def clean_deliverable(
    df: pl.DataFrame, expected_day: date | None = None
) -> tuple[pl.DataFrame, list[dict]]:
    """Coerce the deliverable-positions file into `deliverable_daily` shape."""
    issues: list[dict] = []
    raw = _rename_keep(
        df, DELIV_MAP,
        ("symbol", "date", "series", "quantity_traded",
         "delivery_quantity", "delivery_to_traded"),
    )
    missing = [c for c in DELIV_REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"file missing required columns: {missing} (got {raw.columns})")

    out = raw.with_columns(
        pl.col("symbol").str.strip_chars().str.to_uppercase(),
    )
    if "series" in out.columns:
        out = out.with_columns(
            pl.col("series").str.strip_chars().str.to_uppercase()
        )
    else:
        out = out.with_columns(pl.lit("EQ").alias("series"))
    out = out.with_columns(
        pl.when(pl.col("series").is_null() | (pl.col("series").str.len_chars() == 0))
        .then(pl.lit("EQ"))
        .otherwise(pl.col("series"))
        .alias("series")
    )
    out = _lift_string_col(out, "quantity_traded", to_float=False)
    out = _lift_string_col(out, "delivery_quantity", to_float=False)
    out = _lift_string_col(out, "delivery_to_traded", to_float=True)
    for col in ("quantity_traded", "delivery_quantity"):
        out = out.with_columns(pl.col(col).fill_null(0).cast(pl.Int64))

    out = out.with_columns(
        pl.col("date").str.strip_chars().str.strptime(pl.Date, DATE_FMT, strict=False)
    )
    bad_date = out.filter(pl.col("date").is_null())
    if bad_date.height:
        issues += [
            {"symbol": s, "series": None, "code": "BAD_DATE",
             "message": f"unparsable date {d!r}"}
            for s, d in zip(bad_date["symbol"], bad_date["date"], strict=False)
        ]
    out = out.filter(pl.col("date").is_not_null())

    empty = out.filter(pl.col("symbol").str.len_chars() == 0)
    if empty.height:
        issues.append({"symbol": None, "series": None, "code": "EMPTY_SYMBOL",
                       "message": "empty symbol row"})
    out = out.filter(pl.col("symbol").str.len_chars() > 0)

    if expected_day is not None:
        wrong = out.filter(pl.col("date") != pl.lit(expected_day))
        for sym, d in wrong.select(["symbol", "date"]).iter_rows():
            issues.append({"symbol": sym, "series": None, "code": "DATE_MISMATCH",
                           "message": f"file date {expected_day} but row date {d}"})

    before = out.height
    out = out.unique(subset=["symbol", "series", "date"], keep="first", maintain_order=True)
    if out.height < before:
        issues.append({"symbol": None, "series": None, "code": "DUPLICATE_ROWS",
                       "message": f"dropped {before - out.height} duplicate deliverable rows"})
    return out, issues


def _string_or_lit(out: pl.DataFrame, col: str) -> pl.Expr:
    if col in out.columns:
        return pl.col(col).str.strip_chars()
    return pl.lit(None, dtype=pl.Utf8)


def _string_or_lit_upper(out: pl.DataFrame, col: str) -> pl.Expr:
    if col in out.columns:
        return pl.col(col).str.strip_chars().str.to_uppercase()
    return pl.lit("XX", dtype=pl.Utf8)


def _flag_ohlc(df: pl.DataFrame, issues: list[dict], ident: str = "symbol") -> None:
    if df.height == 0:
        return
    hi = pl.col("high")
    lo = pl.col("low")
    high_bad = (hi + 0.001) < pl.max_horizontal("open", "low", "close")
    low_bad = (lo - 0.001) > pl.min_horizontal("open", "high", "close")
    prev_bad = pl.col("prev_close").is_not_null() & (pl.col("prev_close") < 0)
    bad_cols = [c for c in (ident, "open", "high", "low", "close") if c in df.columns]
    if "prev_close" in df.columns:
        bad = df.filter(high_bad | low_bad | prev_bad)
    else:
        bad = df.filter(high_bad | low_bad)
    for row in bad.select(bad_cols).iter_rows():
        name, o, h, lo, c = row
        issues.append(
            {"symbol": name, "series": None, "code": "OHLC_INVALID",
             "message": f"open={o} high={h} low={lo} close={c} violates OHLC bounds"}
        )