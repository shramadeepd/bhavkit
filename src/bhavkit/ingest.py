"""Ingestion orchestration: download -> parse -> clean -> upsert -> audit."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from .clean import (
    clean_bars,
    clean_deliverable,
    clean_fo,
    clean_index,
    read_bhav_file,
)
from .config import Config
from .db import Database
from .download import (
    STATUS_ERROR,
    STATUS_NON_TRADING,
    DownloadOutcome,
    Fetcher,
)
from .sources import make_source
from .utils import get_logger

log = get_logger()

STATUS_INGESTED = "ingested"
STATUS_SKIPPED = "skipped"

ReaderFn = Callable[[Path], pl.DataFrame]
CleanerFn = Callable[[pl.DataFrame, date | None], tuple[pl.DataFrame, list[dict]]]

PIPELINES: dict[str, tuple[ReaderFn, CleanerFn, str]] = {
    "cm": (read_bhav_file, clean_bars, "upsert_bars"),
    "idx": (read_bhav_file, clean_index, "upsert_index"),
    "fo": (read_bhav_file, clean_fo, "upsert_fo"),
    "deliv": (read_bhav_file, clean_deliverable, "upsert_deliverable"),
}


@dataclass
class IngestSummary:
    product: str
    ingested: int = 0
    skipped: int = 0
    non_trading: int = 0
    errors: int = 0
    rows: int = 0


def update_product(
    db: Database,
    cfg: Config,
    product: str,
    days: list[date],
    force: bool = False,
) -> IngestSummary:
    """Fetch, then ingest, one product over a list of candidate trading days."""
    while True:
        try:
            return asyncio.run(_update_product(db, cfg, product, days, force=force))
        except KeyboardInterrupt:
            log.warning("interrupted; cached files resume on next run")
            raise


async def _update_product(
    db: Database,
    cfg: Config,
    product: str,
    days: list[date],
    force: bool,
) -> IngestSummary:
    fetcher = Fetcher(cfg, make_source(cfg))
    outcomes = await fetcher.fetch_many(product, days)
    summary = IngestSummary(product=product)

    for day in days:
        outcome = outcomes[day]
        if outcome.status == STATUS_ERROR:
            summary.errors += 1
            db.write_ingest_log(product=product, date=day, status=STATUS_ERROR,
                                source_url=outcome.url, error=outcome.error,
                                duration_sec=outcome.duration_sec)
            log.warning("error %s %s: %s", product, day, outcome.error)
            continue
        if outcome.status == STATUS_NON_TRADING:
            summary.non_trading += 1
            db.write_ingest_log(product=product, date=day, status=STATUS_NON_TRADING,
                                source_url=outcome.url, duration_sec=outcome.duration_sec)
            continue
        path = outcome.path
        assert path is not None
        if not force and _already_ingested(db, product, day, outcome.sha256):
            summary.skipped += 1
            continue
        rows = _ingest_one(db, product, day, path, outcome)
        if rows is None:
            summary.errors += 1
            continue
        summary.ingested += 1
        summary.rows += rows

    log.info(
        "%s: %d ingested (%d rows), %d skipped (cache), %d non-trading, %d errors",
        product, summary.ingested, summary.rows, summary.skipped,
        summary.non_trading, summary.errors,
    )
    return summary


def _ingest_one(
    db: Database, product: str, day: date, path: Path, outcome: DownloadOutcome
) -> int | None:
    start = time.monotonic()
    try:
        reader, cleaner, upsert_name = PIPELINES[product]
        raw = reader(path)
        frame, issues = cleaner(raw, day)
        upsert = getattr(db, upsert_name)
        rows = upsert(frame, source_file=path.name)
        db.write_qc_issues(product, day, issues)
        db.write_ingest_log(product=product, date=day, status=STATUS_INGESTED,
                            source_url=outcome.url, file_name=path.name,
                            sha256=outcome.sha256, num_rows=rows,
                            duration_sec=time.monotonic() - start)
        if issues:
            for issue in issues:
                log.debug("qc %s %s %s", product, day, issue["code"])
        return rows
    except Exception as exc:  # noqa: BLE001 - report and continue per-day
        db.write_ingest_log(product=product, date=day, status=STATUS_ERROR,
                            source_url=outcome.url, file_name=path.name,
                            sha256=outcome.sha256, error=str(exc),
                            duration_sec=time.monotonic() - start)
        log.error("failed to ingest %s %s: %s", product, day, exc)
        return None


def _already_ingested(db: Database, product: str, day: date, sha256: str | None) -> bool:
    if sha256 is None:
        return False
    row = db.fetchone(
        "SELECT 1 FROM ingest_log WHERE product=? AND date=? AND status=? AND sha256=?",
        [product, day, STATUS_INGESTED, sha256],
    )
    return row is not None