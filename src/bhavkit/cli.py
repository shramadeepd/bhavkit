"""bhavkit command-line interface."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .calendar import NSE_HOLIDAYS, trading_day_candidates
from .config import (
    Config,
    config_keys,
    default_config_path,
    effective_config_file,
    load_config,
    set_config_option,
    unset_config_option,
    write_default_config,
)
from .db import Database
from .download import base_urls_to_probe
from .download import probe as probe_async
from .export import export_table
from .ingest import update_product
from .metadata import refresh_equity_master
from .query import TEMPLATES, execute_template, repl
from .report import build_report, db_range, refresh_gaps_table, to_json, to_markdown
from .sources import ALL_PRODUCTS
from .utils import get_logger, parse_flexible_date, setup_logging

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Download, clean, and store historical NSE bhavcopy data.")
console = Console()
log = get_logger()

_DEFAULT_END = date.today()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"bhavkit {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback,
        help="Show version and exit.",
    ),
) -> None:
    setup_logging(verbose)


def _resolve_config(
    config: str | None,
    db_path: str | None,
    data_dir: str | None,
) -> Config:
    overrides: dict[str, object] = {}
    if db_path:
        overrides["db_path"] = Path(db_path)
    if data_dir:
        overrides["data_dir"] = Path(data_dir)
    return load_config(config_file=config, overrides=overrides or None)


def _open_db(cfg: Config) -> Database:
    db = Database(cfg.db_path)
    db.bootstrap()
    return db


def _parse_range(
    start: str | None, end: str | None, default_start_days: int
) -> tuple[date, date]:
    end_date = parse_flexible_date(end) if end else _DEFAULT_END
    default_start = end_date - timedelta(days=default_start_days)
    start_date = parse_flexible_date(start) if start else default_start
    return start_date, end_date


def _parse_datasets(raw: str) -> list[str]:
    datasets = [d.strip().lower() for d in raw.split(",") if d.strip()]
    unknown = [d for d in datasets if d not in ALL_PRODUCTS]
    if unknown:
        raise typer.BadParameter(
            f"{unknown} not implemented (datasets: cm, idx, fo, deliv). Got {datasets!r}."
        )
    return datasets


@app.command()
def init(
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Create the database, schema, and cache directories."""
    cfg = _resolve_config(config, db_path, data_dir)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = _open_db(cfg)
    console.print(f"[green]initialized[/green] db={cfg.db_path} "
                  f"data_dir={cfg.data_dir} schema=v{db.schema_version}")

    cfg_file = Path(config) if config else default_config_path()
    if write_default_config(cfg_file):
        console.print(f"[dim]wrote default config[/dim] {cfg_file}")
    else:
        console.print(f"config file: {cfg_file}")
    db.close()


@app.command()
def probe(
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Test NSE archive endpoints and report reachability."""
    cfg = _resolve_config(config, db_path, data_dir)
    table = Table(title="NSE archive endpoints")
    table.add_column("base url")
    table.add_column("status")
    for base in base_urls_to_probe(cfg):
        status = asyncio.run(probe_async(base))
        color = "green" if status == "200" else "red" if status.startswith(("4", "5")) else "yellow"
        table.add_row(base, f"[{color}]{status}[/{color}]")
    console.print(table)
    console.print("tip: if all probes fail, use --source local with a mirror folder.")


def _build_cfg(
    source: str | None,
    local_dir: str | None,
    nse_base_url: str | None,
    config: str | None,
    db_path: str | None,
    data_dir: str | None,
) -> Config:
    overrides: dict[str, object] = {}
    if source:
        overrides["source"] = source
    if local_dir:
        overrides["local_dir"] = Path(local_dir)
    if nse_base_url:
        overrides["nse_base_url"] = nse_base_url
    if db_path:
        overrides["db_path"] = Path(db_path)
    if data_dir:
        overrides["data_dir"] = Path(data_dir)
    return load_config(config_file=config, overrides=overrides or None)


def _execute_update(
    cfg: Config, start_date: date, end_date: date, datasets: str, force: bool
) -> None:
    products = _parse_datasets(datasets)
    days = trading_day_candidates(start_date, end_date)
    db = _open_db(cfg)
    console.print(f"updating {products} over {len(days)} candidate days "
                  f"[{start_date} -> {end_date}] source={cfg.source}")
    for product in products:
        summary = update_product(db, cfg, product, days, force=force)
        statuses = [
            f"ingested={summary.ingested}",
            f"rows={summary.rows}",
            f"non-trading={summary.non_trading}",
            f"errors={summary.errors}",
        ]
        console.print(f"[bold]{product}[/bold]: " + ", ".join(statuses))
    db.close()


@app.command()
def update(
    start: str | None = typer.Option(None, "--start", help="Start date (YYYY-MM-DD)."),
    end: str | None = typer.Option(None, "--end", help="End date (YYYY-MM-DD)."),
    datasets: str = typer.Option("cm", "--datasets",
                                     help="Comma-separated datasets (cm, idx, fo, deliv)."),
    source: str = typer.Option(None, "--source", help="Data source: nse | local."),
    local_dir: str | None = typer.Option(None, "--local-dir", help="Local mirror folder."),
    nse_base_url: str | None = typer.Option(None, "--nse-base-url", help="NSE archive base URL."),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if already ingested."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Download and ingest bhavcopy files for a date range (default: last 7 days)."""
    cfg = _build_cfg(source, local_dir, nse_base_url, config, db_path, data_dir)
    start_date, end_date = _parse_range(start, end, default_start_days=7)
    _execute_update(cfg, start_date, end_date, datasets, force)


@app.command()
def backfill(
    start: str = typer.Option(..., "--start", help="Start date (YYYY-MM-DD). Required."),
    end: str | None = typer.Option(None, "--end", help="End date (default: today)."),
    datasets: str = typer.Option("cm", "--datasets",
                                     help="Comma-separated datasets (cm, idx, fo, deliv)."),
    source: str = typer.Option(None, "--source", help="Data source: nse | local."),
    local_dir: str | None = typer.Option(None, "--local-dir", help="Local mirror folder."),
    nse_base_url: str | None = typer.Option(None, "--nse-base-url", help="NSE archive base URL."),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if already ingested."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Backfill a large historical range; resumable via the file cache."""
    cfg = _build_cfg(source, local_dir, nse_base_url, config, db_path, data_dir)
    start_date, end_date = _parse_range(start, end, default_start_days=7)
    _execute_update(cfg, start_date, end_date, datasets, force)


def _bar_count(db: Database) -> int:
    row = db.fetchone("SELECT count(*) FROM bhav_daily")
    return row[0] if row else 0


def _table_count(db: Database, table: str) -> int:
    row = db.fetchone(f"SELECT count(*) FROM {table}")
    return row[0] if row else 0


@app.command("status")
def status_cmd(
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Show coverage summary from the ingest log."""
    cfg = _resolve_config(config, db_path, data_dir)
    db = _open_db(cfg)
    console.print(f"[bold]db:[/bold] {cfg.db_path} (schema v{db.schema_version}, "
                  f"{_bar_count(db):,} bars)")
    console.print(f"[bold]equity master:[/bold] {_table_count(db, 'equity_master'):,} symbols   "
                  f"[bold]data gaps:[/bold] {_table_count(db, 'data_gaps'):,}")
    table = Table(title="Coverage by month")
    table.add_column("product")
    table.add_column("month")
    table.add_column("data days", justify="right")
    table.add_column("holidays", justify="right")
    table.add_column("errors", justify="right")
    rows = db.query(
        """
        SELECT product, strftime(date, '%Y-%m') AS month,
               count(*) FILTER (WHERE status IN ('ingested', 'skipped')) AS data_days,
               count(*) FILTER (WHERE status = 'not_a_trading_day') AS holidays,
               count(*) FILTER (WHERE status = 'error') AS errors
        FROM ingest_log
        GROUP BY 1, 2 ORDER BY 2 DESC LIMIT 24
        """
    )
    for row in rows.iter_rows():
        table.add_row(*[str(v) for v in row])
    console.print(table)
    db.close()


@app.command()
def report(
    product: str = typer.Option("cm", "--product", help="Product code (cm, idx, fo, deliv)."),
    month: str | None = typer.Option(None, "--month", help="Report a single month (YYYY-MM)."),
    start: str | None = typer.Option(None, "--start", help="Range start (overrides --month)."),
    end: str | None = typer.Option(None, "--end", help="Range end (overrides --month)."),
    out_dir: str | None = typer.Option(None, "--out", help="Directory for report.md/json."),
    no_files: bool = typer.Option(False, "--no-files", help="Print only, write no artifacts."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Generate data-quality report (Markdown + JSON) and refresh data_gaps."""
    from datetime import date as date_type

    cfg = _resolve_config(config, db_path, data_dir)
    db = _open_db(cfg)

    if month:
        lo_date, hi_date = _month_bounds(month)
    elif start or end:
        lo_raw = parse_flexible_date(start) if start else None
        hi_raw = parse_flexible_date(end) if end else None
        lo_date = lo_raw or date_type(2000, 1, 1)
        hi_date = hi_raw or date_type.today()
    else:
        db_lo, db_hi = db_range(db, product)
        lo_date = db_lo or date_type.today() - timedelta(days=366)
        hi_date = db_hi or date_type.today()
    if lo_date > hi_date:
        raise typer.BadParameter(f"range start {lo_date} is after end {hi_date}")

    rep = build_report(db, product, lo_date, hi_date)
    gap_rows = refresh_gaps_table(db, rep)
    console.print(f"[bold]report {product}[/bold] [{lo_date} .. {hi_date}] "
                  f"gaps recorded: {gap_rows}")

    coverage_table = Table(title=f"Coverage — {product}")
    coverage_table.add_column("month")
    coverage_table.add_column("expected", justify="right")
    coverage_table.add_column("data days", justify="right")
    coverage_table.add_column("holidays", justify="right")
    coverage_table.add_column("errors", justify="right")
    coverage_table.add_column("coverage %", justify="right")
    for c in rep.coverage:
        coverage_table.add_row(c.month, str(c.expected), str(c.data_days),
                               str(c.holidays_detected), str(c.errors),
                               f"{c.coverage_pct}%")
    console.print(coverage_table)
    console.print(f"missing attempts: {len(rep.gaps.missing_attempts)} | "
                  f"errors: {len(rep.gaps.errors)} | "
                  f"unknown holidays: {len(rep.gaps.unknown_holidays)} | "
                  f"master drift: {len(rep.master_drift)}")
    cross = ", ".join(f"{t.table}={t.days}d/{t.rows:,}r" for t in rep.cross_tables)
    console.print(f"cross-dataset: {cross}")

    if not no_files:
        out_path = Path(out_dir) if out_dir else (cfg.data_dir / "reports")
        out_path.mkdir(parents=True, exist_ok=True)
        md_path = out_path / f"report_{product}.md"
        json_path = out_path / f"report_{product}.json"
        md_path.write_text(to_markdown(rep))
        json_path.write_text(to_json(rep))
        console.print(f"wrote [green]{md_path}[/green] and [green]{json_path}[/green]")
    db.close()


config_app = typer.Typer(help="Show and edit the TOML configuration file.")
app.add_typer(config_app, name="config")


def _config_error(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]")
    raise typer.Exit(code=2) from None


@config_app.command("show")
def config_show(
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
) -> None:
    """Show the effective (resolved) configuration."""
    cfg = load_config(config_file=config) if config else load_config()
    table = Table(title=f"Effective config — source: {cfg.source}")
    table.add_column("setting")
    table.add_column("value")
    for key in sorted(Config.model_fields):
        value = getattr(cfg, key)
        table.add_row(key, "" if value is None else str(value))
    console.print(table)
    console.print(f"config file: [bold]{config or effective_config_file()}[/bold]"
                  " (CLI flags and BHAV_* env vars override these values)")


@config_app.command("path")
def config_path() -> None:
    """Print the config file that edits would target."""
    console.print(effective_config_file())


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Setting name, e.g. concurrency."),
    value: str = typer.Argument(..., help="New value, e.g. 8."),
) -> None:
    """Update one setting in the config file."""
    cfg_file = effective_config_file()
    try:
        changed = set_config_option(cfg_file, key, value)
    except (KeyError, ValueError) as exc:
        _config_error(exc)
    state = "unchanged" if not changed else "updated"
    console.print(f"[green]{state}[/green] {key} = {value} in {cfg_file}")


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Setting name to remove (falls back to default)."),
) -> None:
    """Remove a setting from the config file."""
    cfg_file = effective_config_file()
    try:
        removed = unset_config_option(cfg_file, key)
    except KeyError as exc:
        _config_error(exc)
    console.print(f"[green]{'removed' if removed else 'not present'}[/green] {key} in {cfg_file}")


@config_app.command("keys")
def config_keys_cmd() -> None:
    """List all valid setting names."""
    console.print(", ".join(config_keys()))


def _month_bounds(month: str) -> tuple[date, date]:
    """Inclusive date range for a YYYY-MM string."""
    import calendar

    year, m = (int(x) for x in month.split("-"))
    last = calendar.monthrange(year, m)[1]
    return date(year, m, 1), date(year, m, last)


master_app = typer.Typer(help="Equity master (symbol metadata).")
app.add_typer(master_app, name="master")


@master_app.command("refresh")
def master_refresh(
    local_file: str | None = typer.Option(None, "--local-file",
                                          help="Read master CSV from disk instead of NSE."),
    source: str = typer.Option(None, "--source", help="Data source: nse | local."),
    nse_base_url: str | None = typer.Option(None, "--nse-base-url", help="NSE archive base URL."),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if cached."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Refresh the equity master (listed equities) from NSE or a local file."""
    cfg = _build_cfg(source, None, nse_base_url, config, db_path, data_dir)
    db = _open_db(cfg)
    summary = refresh_equity_master(db, cfg, local_file=local_file, force=force)
    console.print(f"[bold]master refresh[/bold]: {summary['rows']:,} rows "
                  f"(EQ drift: {summary['drift_count']:,})")
    if summary["drift"]:
        console.print("EQ symbols in bars missing from master (sample): "
                      + ", ".join(summary["drift"][:20]))
    db.close()


@app.command()
def query(
    sql: str | None = typer.Option(None, "--sql", help="Run SQL non-interactively."),
    template: str | None = typer.Option(None, "--template", help="Run a named template query."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Interactive SQL shell (or one-shot --sql / --template)."""
    cfg = _resolve_config(config, db_path, data_dir)
    db = _open_db(cfg)
    if template:
        from .query import _console, _execute

        if template not in TEMPLATES:
            console.print(f"[red]unknown template {template!r}; options:[/red] "
                          + ", ".join(sorted(TEMPLATES)))
            db.close()
            raise typer.Exit(code=2)
        frame = execute_template(db, template)
        c = _console()
        _execute(db, TEMPLATES[template], c) if frame is not None else None
    elif sql:
        from .query import _console, _execute

        _execute(db, sql.rstrip().strip(";") or sql, _console())
    else:
        repl(db)
    db.close()


@app.command()
def export(
    table: str = typer.Option(..., "--table",
                              help="Table to export (bhav_daily, index_daily, fo_daily, "
                                   "deliverable_daily, equity_master)."),
    symbols: str | None = typer.Option(None, "--symbols", help="Comma-separated symbol filter."),
    indexes: str | None = typer.Option(None, "--indexes", help="Comma-separated index filter."),
    series: str | None = typer.Option(None, "--series", help="Series filter (bhav_daily)."),
    start: str | None = typer.Option(None, "--start", help="Start date filter (YYYY-MM-DD)."),
    end: str | None = typer.Option(None, "--end", help="End date filter (YYYY-MM-DD)."),
    fmt: str = typer.Option("parquet", "--format", help="parquet | csv."),
    out: str | None = typer.Option(None, "--out", help="Output file or directory."),
    config: str | None = typer.Option(None, "--config", help="Path to TOML config file."),
    db_path: str | None = typer.Option(None, "--db-path", help="DuckDB database path."),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Cache/download directory."),
) -> None:
    """Export a table to parquet or CSV with optional filters."""
    cfg = _resolve_config(config, db_path, data_dir)
    db = _open_db(cfg)
    start_date = parse_flexible_date(start) if start else None
    end_date = parse_flexible_date(end) if end else None
    out_path = Path(out) if out else (cfg.data_dir / "exports")
    try:
        target = export_table(
            db, table,
            symbols=([s.strip() for s in symbols.split(",") if s.strip()] if symbols else None),
            indexes=([i.strip() for i in indexes.split(",") if i.strip()] if indexes else None),
            series=series,
            start=start_date, end=end_date, fmt=fmt, out=out_path,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        db.close()
        raise typer.Exit(code=2) from None
    console.print(f"exported [bold]{table}[/bold] -> [green]{target}[/green]")
    db.close()


@app.command()
def holidays(
    years: str = typer.Option("2024,2025,2026", "--years", help="Comma-separated years."),
) -> None:
    """Show advisory NSE holidays used for gap reporting."""
    table = Table(title="Advisory NSE holidays (server 404 is authoritative)")
    table.add_column("year")
    table.add_column("date")
    for year in (int(y) for y in years.split(",") if y.strip()):
        for month, day in sorted(NSE_HOLIDAYS.get(year, ())):
            table.add_row(str(year), f"{day:02d}-{month:02d}")
    console.print(table)
    console.print("[dim]advisory: a weekday missing a file is logged as a non-trading "
                  "day regardless of this table.[/dim]")


if __name__ == "__main__":
    app()