"""Interactive SQL shell + read-only template queries over the local DuckDB."""

from __future__ import annotations

import polars as pl

from .db import Database

TEMPLATES: dict[str, str] = {
    "latest": "SELECT MAX(date) AS last_trading_day, COUNT(*) AS rows FROM bhav_daily",
    "table_counts": """
        SELECT 'bhav_daily' AS table, COUNT(*) AS rows FROM bhav_daily
        UNION ALL SELECT 'index_daily', COUNT(*) FROM index_daily
        UNION ALL SELECT 'fo_daily', COUNT(*) FROM fo_daily
        UNION ALL SELECT 'deliverable_daily', COUNT(*) FROM deliverable_daily
        UNION ALL SELECT 'equity_master', COUNT(*) FROM equity_master
    """,
    "top_gainers": """
        SELECT symbol, date, close, prev_close,
               ROUND((close/prev_close - 1) * 100, 2) AS pct
        FROM bhav_daily
        WHERE series='EQ' AND date = (SELECT MAX(date) FROM bhav_daily) AND prev_close > 0
        ORDER BY close/prev_close DESC LIMIT 10
    """,
    "top_losers": """
        SELECT symbol, date, close, prev_close,
               ROUND((close/prev_close - 1) * 100, 2) AS pct
        FROM bhav_daily
        WHERE series='EQ' AND date = (SELECT MAX(date) FROM bhav_daily) AND prev_close > 0
        ORDER BY close/prev_close LIMIT 10
    """,
    "volume_leaders": """
        SELECT symbol, date, total_traded_quantity AS qty,
               ROUND(turnover, 2) AS turnover
        FROM bhav_daily
        WHERE date = (SELECT MAX(date) FROM bhav_daily)
        ORDER BY total_traded_quantity DESC LIMIT 10
    """,
    "delivery_spike": """
        SELECT symbol, date, delivery_qty, total_traded_quantity,
               ROUND(delivery_pct, 2) AS delivery_pct
        FROM bhav_daily
        WHERE date = (SELECT MAX(date) FROM bhav_daily)
          AND total_traded_quantity > 0 AND delivery_pct > 70
        ORDER BY delivery_pct DESC LIMIT 10
    """,
    "fo_most_traded": """
        SELECT instrument, symbol, expiry_date, option_type, strike_price,
               contracts, ROUND(value, 0) AS value
        FROM fo_daily
        WHERE date = (SELECT MAX(date) FROM fo_daily)
        ORDER BY contracts DESC LIMIT 10
    """,
    "fo_open_interest": """
        SELECT instrument, symbol, date, open_interest
        FROM fo_daily
        WHERE symbol = 'NIFTY' AND option_type = 'XX'
        ORDER BY date, expiry_date LIMIT 20
    """,
    "index_history": """
        SELECT index_name, date, close
        FROM index_daily
        WHERE index_name = 'NIFTY 50'
        ORDER BY date LIMIT 30
    """,
    "delivery_ratio": """
        SELECT b.symbol, b.date, b.delivery_qty, d.delivery_quantity
        FROM bhav_daily b
        JOIN deliverable_daily d ON b.symbol = d.symbol AND b.date = d.date
        WHERE b.delivery_qty > 0
        ORDER BY b.date, b.symbol LIMIT 10
    """,
}


_WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER",
                   "TRUNCATE", "ATTACH", "DETACH", "COPY", "EXPORT", "IMPORT",
                   "SET", "LOAD", "PRAGMA")


def run_sql(db: Database, sql: str) -> pl.DataFrame:
    """Execute read-only SQL and return the result frame."""
    head = sql.lstrip().lstrip("(")
    first = head.split(maxsplit=1)[0].upper() if head else ""
    if first in _WRITE_KEYWORDS:
        raise ValueError(f"read-only shell: {first} statements are not allowed")
    return db.query(sql)


def execute_template(db: Database, name: str) -> pl.DataFrame | None:
    sql = TEMPLATES.get(name)
    if sql is None:
        return None
    return run_sql(db, sql)


def repl(db: Database) -> None:
    r"""Interactive SQL REPL. \h help, \t templates, \r <name> run a template,
    \d relations, \q quit."""
    console = _console()
    console.print("[bold]bhavkit query shell[/bold] (duckdb). Type SQL ending in ';', "
                  "or \\h for help, \\q to quit.")
    buffer: list[str] = []
    while True:
        try:
            prompt = "   -> " if buffer else "bhavkit> "
            line = input(prompt)
        except EOFError:
            console.print()
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ("\\q", "\\quit", "quit", "exit"):
            break
        if stripped.startswith("\\"):
            _handle_meta(db, stripped, console)
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            sql = "\n".join(buffer)
            buffer = []
            _execute(db, sql, console)


def _execute(db: Database, sql: str, console) -> None:
    try:
        df = run_sql(db, sql)
    except Exception as exc:  # noqa: BLE001 - interactive
        console.print(f"[red]error:[/red] {exc}")
        return
    if df.is_empty():
        console.print("[dim]0 rows[/dim]")
        return
    if df.height > 500:
        console.print(f"[dim]{df.height} rows (showing first 500)[/dim]")
        df = df.head(500)
    table = _table(df)
    console.print(table)


def _handle_meta(db: Database, cmd: str, console) -> None:
    if cmd in ("\\h", "\\help"):
        console.print(
            "\\d            list tables\n"
            "\\t            list template queries\n"
            "\\r <name>     run a template query\n"
            "\\q            quit\n"
            "SQL           any read-only SQL ending in ';'"
        )
    elif cmd in ("\\d", "\\tables"):
        _execute(db, "SHOW TABLES", console)
    elif cmd in ("\\t", "\\templates"):
        for name, sql in TEMPLATES.items():
            console.print(f"[cyan]{name}[/cyan]: {sql.splitlines()[0][:80]}")
    elif cmd.startswith("\\r"):
        name = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else ""
        if not name:
            console.print("usage: \\r <template-name>")
            return
        if name not in TEMPLATES:
            console.print(f"[red]unknown template {name!r}; try \\t[/red]")
            return
        _execute(db, TEMPLATES[name], console)
    else:
        console.print(f"[red]unknown command {cmd!r}; \\h for help[/red]")


def _console():
    from rich.console import Console

    return Console()


def _table(df: pl.DataFrame):
    from rich.table import Table

    table = Table(show_lines=False)
    for col in df.columns:
        table.add_column(col)
    for row in df.iter_rows():
        table.add_row(*[str(v) for v in row])
    return table