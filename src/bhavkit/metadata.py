"""Equity master (symbol metadata) refresh and drift detection."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import httpx
import polars as pl

from .config import Config
from .db import Database
from .utils import get_logger

log = get_logger()

MASTER_FILE = "EQUITY_L.csv"
MASTER_SUBURL = "/content/equities/EQUITY_L.csv"

# EQUITY_L.csv headers -> equity_master columns (older files used COMPANY NAME).
MASTER_HEADERS = {
    "SYMBOL": "symbol",
    "NAME OF COMPANY": "name",
    "COMPANY NAME": "name",
    "SERIES": "series",
    "DATE OF LISTING": "listing_date",
    "ISIN NUMBER": "isin",
    "ISIN": "isin",
}

MASTER_DTYPES = {
    "SYMBOL": pl.Utf8,
    "NAME OF COMPANY": pl.Utf8,
    "COMPANY NAME": pl.Utf8,
    "SERIES": pl.Utf8,
    "DATE OF LISTING": pl.Utf8,
    "ISIN NUMBER": pl.Utf8,
    "ISIN": pl.Utf8,
}

_DT_FMTS = ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d")


def refresh_equity_master(db: Database, cfg: Config, local_file: str | Path | None = None,
                          force: bool = False) -> dict:
    """Fetch/parse the equity master and upsert into `equity_master`.

    Pass `local_file` to read from disk (testing / offline mirrors).
    Returns a summary dict: {rows, inserted, drift, drift_count}.
    """
    started = time.monotonic()
    if local_file is not None:
        path = Path(local_file)
    else:
        path = _fetch_master(cfg, force=force)
    try:
        raw = pl.read_csv(path, infer_schema_length=0)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"failed to read equity master {path}: {exc}") from exc

    df = _clean_master(raw)
    rows = db.upsert_master(df)
    sha = _sha256(path)
    db.write_ingest_log(product="master", date=date.today(), status="ingested",
                        source_url=str(path), file_name=path.name, sha256=sha,
                        num_rows=rows, duration_sec=time.monotonic() - started)
    drift, drift_count = _drift(db)
    log.info("equity master: %d rows, %d EQ symbols in bars missing from master",
             rows, drift_count)
    return {"rows": rows, "drift": drift, "drift_count": drift_count}


def _fetch_master(cfg: Config, force: bool = False) -> Path:
    dest = cfg.data_dir / "cache" / "master" / MASTER_FILE
    if not force and dest.is_file() and dest.stat().st_size > 0:
        return dest
    url = f"{cfg.nse_base_url}{MASTER_SUBURL}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(url, headers={"User-Agent": cfg.user_agent}, timeout=cfg.timeout,
                     follow_redirects=True)
    if resp.status_code != 200:
        raise ValueError(f"master fetch failed: HTTP {resp.status_code} ({url})")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_bytes(resp.content)
    tmp.replace(dest)
    return dest


def _clean_master(raw: pl.DataFrame) -> pl.DataFrame:
    normalized = {h.strip().upper(): target for h, target in MASTER_HEADERS.items()}
    rename = {c: normalized[c.strip().upper()] for c in raw.columns
              if c.strip().upper() in normalized}
    out = raw.rename(rename) if rename else raw
    cols = [c for c in ("symbol", "name", "series", "isin", "listing_date")
            if c in out.columns]
    if "symbol" not in cols:
        raise ValueError(f"master missing SYMBOL column (got {raw.columns})")
    out = out.select(cols).with_columns(
        pl.col("symbol").str.strip_chars().str.to_uppercase()
    )
    if "series" in out.columns:
        out = out.with_columns(pl.col("series").str.strip_chars().str.to_uppercase())
    if "name" in out.columns:
        out = out.with_columns(pl.col("name").str.strip_chars())
    if "isin" in out.columns:
        out = out.with_columns(pl.col("isin").str.strip_chars().str.to_uppercase())
    if "listing_date" in out.columns:
        out = out.with_columns(_parse_dates(pl.col("listing_date")).alias("listing_date"))
        out = out.with_columns(pl.col("listing_date").cast(pl.Date, strict=False))

    out = out.filter(pl.col("symbol").str.len_chars() > 0)
    # Prefer EQ over other series when a symbol repeats across rows.
    out = out.with_columns(
        (pl.col("series") != "EQ").cast(pl.Int8).alias("_series_rank")
    )
    sort_cols = ["_series_rank"]
    if "listing_date" in out.columns:
        sort_cols.append("listing_date")
    out = out.sort(sort_cols)
    out = out.unique(subset=["symbol"], keep="first", maintain_order=True)
    return out.drop([c for c in out.columns if c.startswith("_")])


def _parse_dates(col: pl.Expr) -> pl.Expr:
    """Parse a string date column across several formats (lenient)."""
    parsed: pl.Expr = pl.lit(None, dtype=pl.Date)
    for fmt in _DT_FMTS:
        parsed = pl.coalesce(
            parsed, col.str.strptime(pl.Date, fmt, strict=False)
        )
    return parsed


def _drift(db: Database) -> tuple[list[str], int]:
    """EQ symbols present in bars but missing from the equity master."""
    if (not db.fetchone("SELECT 1 FROM equity_master LIMIT 1")):
        return [], 0
    df = db.query(
        """
        SELECT DISTINCT b.symbol FROM bhav_daily b
        WHERE b.series = 'EQ'
          AND b.symbol NOT IN (SELECT symbol FROM equity_master)
        ORDER BY 1
        """
    )
    symbols = [s for s, in df.iter_rows()]
    return symbols, len(symbols)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()