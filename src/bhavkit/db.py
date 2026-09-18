from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

SCHEMA_VERSION = 2

BARS_COLUMNS = (
    "symbol",
    "series",
    "date",
    "prev_close",
    "open",
    "high",
    "low",
    "last",
    "close",
    "avg_price",
    "total_traded_quantity",
    "turnover",
    "no_of_trades",
    "delivery_qty",
    "delivery_pct",
    "source_file",
)

INDEX_COLUMNS = (
    "index_name",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "source_file",
)

FO_COLUMNS = (
    "instrument",
    "symbol",
    "expiry_date",
    "option_type",
    "strike_price",
    "date",
    "open",
    "high",
    "low",
    "close",
    "settle_price",
    "contracts",
    "value",
    "open_interest",
    "change_in_oi",
    "source_file",
)

DELIVERABLE_COLUMNS = (
    "symbol",
    "date",
    "series",
    "isin",
    "quantity_traded",
    "delivery_quantity",
    "delivery_to_traded",
    "source_file",
)


class Database:
    """Thin wrapper around a local DuckDB database file."""

    def __init__(self, path: Path):
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))
        self._conn.execute("SET threads = 4")

    def bootstrap(self) -> None:
        """Apply the schema (idempotent) and record the current version."""
        legacy = self._deliverable_pk_is_legacy()
        if legacy:
            # v1->v2: deliverable_daily PK was (symbol, date); widening to
            # (symbol, series, date) requires a table rebuild. Preserve rows.
            self._conn.execute("ALTER TABLE deliverable_daily RENAME TO deliverable_daily_legacy")
        schema = (Path(__file__).parent / "schema.sql").read_text()
        self._conn.execute(schema)
        if legacy:
            present = self._conn.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE table_name='deliverable_daily_legacy'"
            ).fetchone()
            if present and present[0]:
                self._conn.execute(
                    "INSERT OR REPLACE INTO deliverable_daily "
                    "(symbol, series, date, isin, quantity_traded, delivery_quantity, "
                    "delivery_to_traded, source_file) "
                    "SELECT symbol, COALESCE(NULLIF(series, ''), 'EQ'), date, isin, "
                    "quantity_traded, delivery_quantity, delivery_to_traded, source_file "
                    "FROM deliverable_daily_legacy"
                )
                self._conn.execute("DROP TABLE deliverable_daily_legacy")
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)",
            [SCHEMA_VERSION],
        )

    def _deliverable_pk_is_legacy(self) -> bool:
        try:
            row = self._conn.execute(
                """
                SELECT constraint_column_names FROM duckdb_constraints()
                WHERE table_name='deliverable_daily' AND constraint_type='PRIMARY KEY'
                """
            ).fetchone()
        except Exception:  # noqa: BLE001 - constraints() unavailable in old duckdb
            return False
        if row is None:
            return False
        cols = list(row[0])
        return cols == ["symbol", "date"] and SCHEMA_VERSION > 1

    @property
    def schema_version(self) -> int | None:
        row = self._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def upsert_bars(self, df: pl.DataFrame, source_file: str) -> int:
        """Upsert cleaned daily bars by PK (symbol, series, date). Returns row count."""
        return self._upsert("bhav_daily", BARS_COLUMNS, df, source_file)

    def upsert_index(self, df: pl.DataFrame, source_file: str) -> int:
        """Upsert index daily bars by PK (index_name, date). Returns row count."""
        return self._upsert("index_daily", INDEX_COLUMNS, df, source_file)

    def upsert_fo(self, df: pl.DataFrame, source_file: str) -> int:
        """Upsert F&O bars by PK (instrument, symbol, expiry, type, strike, date)."""
        return self._upsert("fo_daily", FO_COLUMNS, df, source_file)

    def upsert_deliverable(self, df: pl.DataFrame, source_file: str) -> int:
        """Upsert deliverable positions by PK (symbol, date). Returns row count."""
        return self._upsert("deliverable_daily", DELIVERABLE_COLUMNS, df, source_file)

    def _upsert(
        self, table: str, columns: tuple[str, ...], df: pl.DataFrame, source_file: str
    ) -> int:
        frame = df.with_columns(pl.lit(source_file).alias("source_file"))
        for col in columns:
            if col not in frame.columns:
                frame = frame.with_columns(pl.lit(None).alias(col))
        frame = frame.select(columns)
        cols = ", ".join(columns)
        placeholders = ", ".join(columns)
        self._conn.register("_stage", frame)
        self._conn.execute(
            f"INSERT OR REPLACE INTO {table} ({cols}) "
            f"SELECT {placeholders} FROM _stage"
        )
        self._conn.unregister("_stage")
        return frame.height

    def upsert_master(self, df: pl.DataFrame) -> int:
        """Upsert equity master rows by PK (symbol). Returns row count."""
        cols = ("symbol", "name", "isin", "series", "listing_date", "status", "updated_at")
        frame = df.with_columns(
            pl.lit("listed").alias("status"),
            pl.lit(datetime.now()).alias("updated_at"),
        )
        for col in ("name", "isin", "series", "listing_date"):
            if col not in frame.columns:
                frame = frame.with_columns(pl.lit(None).alias(col))
        self._conn.register("_master_stage", frame.select(cols))
        self._conn.execute(
            "INSERT OR REPLACE INTO equity_master (symbol, name, isin, series, "
            "listing_date, status, updated_at) "
            "SELECT symbol, name, isin, series, listing_date, status, updated_at "
            "FROM _master_stage"
        )
        self._conn.unregister("_master_stage")
        return frame.height

    def write_ingest_log(
        self,
        *,
        product: str,
        date: object,
        status: str,
        source_url: str | None = None,
        file_name: str | None = None,
        sha256: str | None = None,
        num_rows: int = 0,
        error: str | None = None,
        duration_sec: float | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ingest_log
                (product, date, source_url, file_name, sha256, num_rows, status,
                 error, duration_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [product, date, source_url, file_name, sha256, num_rows, status,
             error, duration_sec],
        )

    def write_qc_issues(self, product: str, date: object, issues: list[dict]) -> None:
        if not issues:
            return
        self._conn.executemany(
            """
            INSERT INTO qc_issues (product, date, symbol, series, code, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (product, date, i.get("symbol"), i.get("series"), i["code"], i["message"])
                for i in issues
            ],
        )

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        return self._conn.execute(sql, params or []).pl()

    def fetchone(self, sql: str, params: list | None = None) -> tuple | None:
        return self._conn.execute(sql, params or []).fetchone()

    def cr(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def close(self) -> None:
        self._conn.close()