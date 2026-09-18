"""Data-quality reports: monthly coverage, gap detection, anomalies.

Renders Markdown + JSON artifacts, and refreshes the derived `data_gaps`
table used by `status`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from .calendar import is_nse_holiday, trading_day_candidates, weekdays
from .db import Database

MAX_ANOMALY_SAMPLES = 5


@dataclass
class MonthCoverage:
    product: str
    month: str
    expected: int
    data_days: int
    holidays_detected: int
    errors: int
    coverage_pct: float


@dataclass
class GapData:
    product: str
    start: date
    end: date
    missing_attempts: list[date]
    errors: list[date]
    unknown_holidays: list[date]


@dataclass
class AnomalyBucket:
    code: str
    count: int
    samples: list[dict]


@dataclass
class CrossTable:
    """Cross-dataset coverage info for an auxiliary table within a range."""
    table: str
    days: int
    rows: int
    first: date | None
    last: date | None


@dataclass
class Report:
    product: str
    generated_at: str
    start: date
    end: date
    coverage: list[MonthCoverage]
    gaps: GapData
    anomalies: list[AnomalyBucket]
    master_drift: list[str]
    cross_tables: list[CrossTable]


def db_range(db: Database, product: str) -> tuple[date | None, date | None]:
    row = db.fetchone(
        "SELECT min(date), max(date) FROM ingest_log WHERE product=? AND status IN "
        "('ingested', 'skipped', 'error', 'not_a_trading_day')",
        [product],
    )
    if not row or row[0] is None:
        return None, None
    return row[0], row[1]


def month_coverage(db: Database, product: str, start: date, end: date) -> list[MonthCoverage]:
    coverage: list[MonthCoverage] = []
    month_start = start.replace(day=1)
    while month_start <= end:
        month_end = _month_end(month_start)
        lo, hi = max(start, month_start), min(end, month_end)
        expected = len(trading_day_candidates(lo, hi))
        rows = db.query(
            """
            SELECT
                count(*) FILTER (WHERE status IN ('ingested', 'skipped')) AS data_days,
                count(*) FILTER (WHERE status = 'not_a_trading_day') AS holidays,
                count(*) FILTER (WHERE status = 'error') AS errors
            FROM ingest_log
            WHERE product = ? AND date BETWEEN ? AND ?
            """,
            [product, lo, hi],
        )
        row = rows.row(0)
        coverage.append(
            MonthCoverage(
                product=product,
                month=month_start.strftime("%Y-%m"),
                expected=expected,
                data_days=row[0],
                holidays_detected=row[1],
                errors=row[2],
                coverage_pct=round(100 * row[0] / expected, 2) if expected else 100.0,
            )
        )
        month_start = _month_end(month_start) + timedelta(days=1)
    return coverage


def detect_gaps(db: Database, product: str, start: date, end: date) -> GapData:
    logged = set(
        db.query(
            "SELECT date, status FROM ingest_log WHERE product=? AND date BETWEEN ? AND ?",
            [product, start, end],
        )
        .select("date", "status")
        .iter_rows()
    )
    by_date: dict[date, str] = {d: s for d, s in logged}

    missing: list[date] = []
    errors: list[date] = []
    unknown_holidays: list[date] = []
    for day in weekdays(start, end):
        status = by_date.get(day)
        if status is None:
            if not is_nse_holiday(day):
                missing.append(day)
        elif status == "error":
            errors.append(day)
        elif status == "not_a_trading_day" and not is_nse_holiday(day):
            # server says holiday but advisory calendar did not know about it
            unknown_holidays.append(day)
    return GapData(product, start, end, missing, errors, unknown_holidays)


ANOMALY_QUERIES: dict[str, str] = {
    "EXTREME_MOVE": (
        "SELECT symbol, date, prev_close, close FROM bhav_daily "
        "WHERE series='EQ' AND prev_close > 0 AND date BETWEEN ? AND ? "
        "AND abs(close/prev_close - 1) > 0.25"
    ),
    "ZERO_VOLUME_WITH_TRADES": (
        "SELECT symbol, date, total_traded_quantity, no_of_trades FROM bhav_daily "
        "WHERE total_traded_quantity <= 0 AND no_of_trades > 0 "
        "AND date BETWEEN ? AND ?"
    ),
    "NEGATIVE_PRICE": (
        "SELECT symbol, date, open, high, low, close FROM bhav_daily "
        "WHERE (close < 0 OR high < 0 OR open < 0 OR low < 0) AND date BETWEEN ? AND ?"
    ),
    "DELIVERY_MISMATCH": (
        "SELECT b.symbol, b.date, b.delivery_qty, d.delivery_quantity "
        "FROM bhav_daily b JOIN deliverable_daily d "
        "ON b.symbol = d.symbol AND b.date = d.date "
        "WHERE d.series='EQ' AND b.delivery_qty > 0 AND b.delivery_qty <> d.delivery_quantity "
        "AND d.date BETWEEN ? AND ?"
    ),
}


def detect_anomalies(
    db: Database,
    start: date,
    end: date,
    max_samples: int = MAX_ANOMALY_SAMPLES,
) -> list[AnomalyBucket]:
    buckets: list[AnomalyBucket] = []
    for code, sql in ANOMALY_QUERIES.items():
        row = db.fetchone(_count_of(sql), [start, end])
        count = row[0] if row else 0
        sample_df = db.query(f"{sql} ORDER BY date, symbol LIMIT {max_samples}", [start, end])
        samples = [{k: str(v) for k, v in r.items()} for r in sample_df.iter_rows(named=True)]
        buckets.append(AnomalyBucket(code=code, count=count, samples=samples))
    return buckets


def _count_of(sql: str) -> str:
    """Count the rows matched by a predicate query (drops ORDER/LIMIT)."""
    stripped = re.sub(r"\s*ORDER\s+BY\s+.*", "", sql, flags=re.S)
    stripped = re.sub(r"\s*LIMIT\s+\d+.*", "", stripped, flags=re.S)
    return f"SELECT count(*) {stripped[stripped.index(' FROM '):]}"


def master_drift(db: Database) -> list[str]:
    row = db.fetchone(
        "SELECT count(*) FROM equity_master"
    )
    if not row or row[0] == 0:
        return []
    return [
        s for s, in db.query(
            """
            SELECT DISTINCT b.symbol FROM bhav_daily b
            WHERE b.series='EQ'
              AND b.symbol NOT IN (SELECT symbol FROM equity_master)
            ORDER BY 1
            """
        ).iter_rows()
    ]


def cross_tables(db: Database, start: date, end: date) -> list[CrossTable]:
    """Coverage of the auxiliary tables (index/fo/deliverable) within a range."""
    out: list[CrossTable] = []
    for tbl in ("index_daily", "fo_daily", "deliverable_daily"):
        row = db.fetchone(
            f"SELECT count(DISTINCT date), count(*), min(date), max(date) "
            f"FROM {tbl} WHERE date BETWEEN ? AND ?",
            [start, end],
        )
        if row is None:
            row = (0, 0, None, None)
        days, rows, first, last = row
        out.append(CrossTable(table=tbl, days=days, rows=rows, first=first, last=last))
    return out


def build_report(db: Database, product: str, start: date, end: date) -> Report:
    return Report(
        product=product,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        start=start,
        end=end,
        coverage=month_coverage(db, product, start, end),
        gaps=detect_gaps(db, product, start, end),
        anomalies=detect_anomalies(db, start, end),
        master_drift=master_drift(db),
        cross_tables=cross_tables(db, start, end),
    )


def refresh_gaps_table(db: Database, report: Report) -> int:
    """Rebuild the derived data_gaps table from a report. Returns row count."""
    db.cr().execute("DELETE FROM data_gaps WHERE product = ?", [report.product])
    inserts = []
    for day in report.gaps.missing_attempts:
        inserts.append((report.product, day, "missing_attempt", "no ingest record"))
    for day in report.gaps.errors:
        inserts.append((report.product, day, "ingest_error", "ingest failed"))
    for day in report.gaps.unknown_holidays:
        inserts.append((report.product, day, "unknown_holiday", "server reported non-trading day"))
    last_date = report.end
    if report.master_drift:
        preview = ", ".join(report.master_drift[:5])
        inserts.append(
            (
                report.product,
                last_date,
                "symbol_not_in_master",
                f"{len(report.master_drift)} EQ symbols with bars missing from master"
                f"{f' (e.g. {preview})' if preview else ''}",
            )
        )
    if inserts:
        db.cr().executemany(
            "INSERT INTO data_gaps (product, date, gap_type, detail) VALUES (?, ?, ?, ?)",
            inserts,
        )
    return len(inserts)


def to_markdown(report: Report) -> str:
    lines = [
        f"# bhavkit data-quality report — {report.product}",
        "",
        f"- generated: {report.generated_at}",
        f"- range: {report.start} .. {report.end}",
        f"- gaps: {len(report.gaps.missing_attempts)} missing, "
        f"{len(report.gaps.errors)} errors, "
        f"{len(report.gaps.unknown_holidays)} unknown holidays",
        "",
        "## Monthly coverage",
        "",
        "| month | expected | data days | holidays | errors | coverage |",
        "| ------ | -------: | --------: | -------: | -----: | -------: |",
    ]
    for c in report.coverage:
        lines.append(
            f"| {c.month} | {c.expected} | {c.data_days} | {c.holidays_detected} "
            f"| {c.errors} | {c.coverage_pct}% |"
        )
    lines += ["", "## Gaps", ""]
    if report.gaps.missing_attempts:
        lines.append("Missing attempts (weekdays with no record):")
        lines.append(" - " + ", ".join(str(d) for d in report.gaps.missing_attempts[:50]))
        lines.append("")
    if report.gaps.errors:
        lines.append("Ingest errors:")
        lines.append(" - " + ", ".join(str(d) for d in report.gaps.errors))
        lines.append("")
    if report.gaps.unknown_holidays:
        lines.append("Unknown holidays detected by source (add to calendar.py):")
        lines.append(" - " + ", ".join(str(d) for d in report.gaps.unknown_holidays))
        lines.append("")
    lines += ["## Anomalies", ""]
    if not report.anomalies:
        lines.append("none")
    for bucket in report.anomalies:
        lines.append(f"### {bucket.code} ({bucket.count})")
        if bucket.samples:
            lines.append("")
            lines.append("| " + " | ".join(bucket.samples[0].keys()) + " |")
            lines.append("| " + " | ".join("---" for _ in bucket.samples[0]) + " |")
            for row in bucket.samples:
                lines.append("| " + " | ".join(str(v) for v in row.values()) + " |")
        lines.append("")
    lines += ["## Equity master drift", ""]
    if report.master_drift:
        drift = ", ".join(report.master_drift[:50])
        lines.append(f"EQ symbols with bars but missing from the master: {drift}")
    else:
        lines.append("none")
    lines += ["", "## Cross-dataset coverage", ""]
    if report.cross_tables:
        lines.append("| table | days | rows | first | last |")
        lines.append("| --- | ---: | ---: | --- | --- |")
        for t in report.cross_tables:
            first_last = f"{t.first or '-'} | {t.last or '-'}"
            lines.append(f"| {t.table} | {t.days} | {t.rows} | {first_last} |")
    else:
        lines.append("none available in range")
    lines.append("")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    data = asdict(report)
    return json.dumps(data, indent=2, default=str)


def _month_end(day: date) -> date:
    import calendar

    return day.replace(day=calendar.monthrange(day.year, day.month)[1])