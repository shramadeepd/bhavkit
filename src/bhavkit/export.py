"""Export local tables to Parquet / CSV with optional filters."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .db import Database

EXPORTABLE: dict[str, tuple[str, str | None]] = {
    # name -> (duckdb table, symbol-column or None)
    "bhav_daily": ("bhav_daily", "symbol"),
    "index_daily": ("index_daily", "index_name"),
    "fo_daily": ("fo_daily", "symbol"),
    "deliverable_daily": ("deliverable_daily", "symbol"),
    "equity_master": ("equity_master", None),
}

_SAFE_IDENT = frozenset(EXPORTABLE)


def _lit(value) -> str:
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def export_table(
    db: Database,
    table: str,
    *,
    symbols: list[str] | None = None,
    indexes: list[str] | None = None,
    series: str | None = None,
    start: date | None = None,
    end: date | None = None,
    fmt: str = "parquet",
    out: Path | None = None,
) -> Path:
    """Export a table to `out` (file or dir); default dir is data_dir/exports."""
    if table not in EXPORTABLE:
        raise ValueError(f"unknown export table {table!r}; must be one of {sorted(EXPORTABLE)}")
    duck_tbl, sym_col = EXPORTABLE[table]
    if fmt not in {"parquet", "csv"}:
        raise ValueError(f"format must be parquet|csv, got {fmt!r}")

    clauses: list[str] = []
    if symbols and sym_col:
        quoting = ", ".join(_lit(s) for s in symbols)
        clauses.append(f"{sym_col} IN ({quoting})")
    if indexes and sym_col == "index_name":
        quoting = ", ".join(_lit(i) for i in indexes)
        clauses.append(f"index_name IN ({quoting})")
    if series and table == "bhav_daily":
        clauses.append(f"series = {_lit(series)}")
    if table != "equity_master":
        if start:
            clauses.append(f"date >= {_lit(start)}")
        if end:
            clauses.append(f"date <= {_lit(end)}")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM {duck_tbl}{where} ORDER BY 1, 2"

    if out is None:
        raise ValueError("out path must be provided")
    out = out.resolve()
    if out.suffix.lower() in {".parquet", ".csv"}:
        target = out
    else:
        out.mkdir(parents=True, exist_ok=True)
        tag = "-".join(p for p in filter(None, [
            ",".join(symbols) if symbols else "",
            ",".join(indexes) if indexes else "",
            series or "",
            str(start) if start else "",
            str(end) if end else "",
        ])) or "all"
        tag = tag.replace(",", "+").replace(" ", "_")
        target = out / f"{table}_{tag}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "parquet":
        db.cr().execute(f"COPY ({sql}) TO ? (FORMAT PARQUET)", [str(target)])
    else:
        db.cr().execute(f"COPY ({sql}) TO ? (FORMAT CSV, HEADER)", [str(target)])
    return target