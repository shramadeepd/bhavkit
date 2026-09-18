# bhavkit CLI reference

`bhavkit` is a Typer CLI. This page documents every command and option; run
`bhavkit <command> --help` for the live version. Global option: `--verbose` / `-v`.

Three thin override flags exist on almost every command (`--config`, `--db-path`,
`--data-dir`); they take precedence over the config file and `BHAV_*` env vars
(see the README's configuration section).

```
Usage: bhavkit [OPTIONS] COMMAND [ARGS]...

Download, clean, and store historical NSE bhavcopy data.

Options:
  --verbose  -v        Debug logging.
  --help               Show this message and exit.

Commands:
  init      Create the database, schema, and cache directories.
  probe     Test NSE archive endpoints and report reachability.
  update    Download and ingest bhavcopy files for a date range (default: last 7 days).
  backfill  Backfill a large historical range; resumable via the file cache.
  status    Show coverage summary from the ingest log.
  report    Generate data-quality report (Markdown + JSON) and refresh data_gaps.
  query     Interactive SQL shell (or one-shot --sql / --template).
  export    Export a table to parquet or CSV with optional filters.
  holidays  Show advisory NSE holidays used for gap reporting.
  master    Equity master (symbol metadata).
  config    Show and edit the TOML configuration file.
```

---

## `bhavkit init`

Create the DuckDB database, apply/upgrade the schema, and create cache dirs.

```
Usage: bhavkit init [OPTIONS]

Options:
  --config    <str>   Path to TOML config file.
  --db-path   <str>   DuckDB database path.
  --data-dir  <str>   Cache/download directory.
  --help              Show this message and exit.
```

## `bhavkit probe`

Test the configured NSE base URLs and print reachability (HTTP status) for each.

```
Usage: bhavkit probe [OPTIONS]

Options:
  --config    <str>   Path to TOML config file.
  --db-path   <str>   DuckDB database path.
  --data-dir  <str>   Cache/download directory.
  --help              Show this message and exit.
```

## `bhavkit update`

Download and ingest bhavcopy data for a date range. Defaults to the last 7 days.

```
Usage: bhavkit update [OPTIONS]

Options:
  --start           <str>  Start date (YYYY-MM-DD).
  --end             <str>  End date (YYYY-MM-DD).
  --datasets        <str>  Comma-separated datasets (cm, idx, fo, deliv).
                           [default: cm]
  --source          <str>  Data source: nse | local.
  --local-dir       <str>  Local mirror folder.
  --nse-base-url    <str>  NSE archive base URL.
  --force                  Re-ingest even if already ingested.
  --config          <str>  Path to TOML config file.
  --db-path         <str>  DuckDB database path.
  --data-dir        <str>  Cache/download directory.
  --help                  Show this message and exit.
```

## `bhavkit backfill`

Same engine as `update`, sized for large historical ranges. Required `--start`;
the cache makes re-runs resumable (an interrupted run picks up where it stopped).

```
Usage: bhavkit backfill [OPTIONS]

Options:
  *  --start           <str>  Start date (YYYY-MM-DD). Required. [required]
     --end             <str>  End date (default: today).
     --datasets        <str>  Comma-separated datasets (cm, idx, fo, deliv).
                              [default: cm]
     --source          <str>  Data source: nse | local.
     --local-dir       <str>  Local mirror folder.
     --nse-base-url    <str>  NSE archive base URL.
     --force                  Re-ingest even if already ingested.
     --config          <str>  Path to TOML config file.
     --db-path         <str>  DuckDB database path.
     --data-dir        <str>  Cache/download directory.
     --help                  Show this message and exit.
```

## `bhavkit master`

### `master refresh`

Refresh the equity master (listed equities, symbol metadata) from NSE's
`EQUITY_L.csv` or a local file.

```
Usage: bhavkit master refresh [OPTIONS]

Options:
  --local-file       <str>  Read master CSV from disk instead of NSE.
  --source           <str>  Data source: nse | local.
  --nse-base-url     <str>  NSE archive base URL.
  --force                   Re-fetch even if cached.
  --config           <str>  Path to TOML config file.
  --db-path          <str>  DuckDB database path.
  --data-dir         <str>  Cache/download directory.
  --help                    Show this message and exit.
```

## `bhavkit status`

Show bar/master/gap totals plus a coverage-by-month table from `ingest_log`.

```
Usage: bhavkit status [OPTIONS]

Options:
  --config    <str>   Path to TOML config file.
  --db-path   <str>   DuckDB database path.
  --data-dir  <str>   Cache/download directory.
  --help              Show this message and exit.
```

## `bhavkit report`

Generate a data-quality report (Markdown + JSON) and refresh the `data_gaps`
table. Without `--month`/`--start`/`--end`, the range is derived from the data
itself.

```
Usage: bhavkit report [OPTIONS]

Options:
  --product   <str>  Product code (cm, idx, fo, deliv). [default: cm]
  --month     <str>  Report a single month (YYYY-MM).
  --start     <str>  Range start (overrides --month).
  --end       <str>  Range end (overrides --month).
  --out       <str>  Directory for report.md/json.
  --no-files         Print only, write no artifacts.
  --config    <str>  Path to TOML config file.
  --db-path   <str>  DuckDB database path.
  --data-dir  <str>  Cache/download directory.
  --help             Show this message and exit.
```

Write location: `<data_dir>/reports/report_<product>.md` + `.json` (or `--out`).
The report contains monthly coverage, gaps, anomaly buckets, equity-master
drift, and cross-dataset coverage.

## `bhavkit query`

Interactive read-only SQL shell. Write statements are blocked. With no args it
drops into the REPL; one-shot via `--sql` or `--template`.

```
Usage: bhavkit query [OPTIONS]

Options:
  --sql        <str>  Run SQL non-interactively.
  --template   <str>  Run a named template query.
  --config     <str>  Path to TOML config file.
  --db-path    <str>  DuckDB database path.
  --data-dir   <str>  Cache/download directory.
  --help              Show this message and exit.
```

REPL commands:

```
\q            quit
\h            help
\d            list tables
\t            list template queries
\r <name>     run a template query
SQL;          run any read query ending in ';'
```

Templates: `latest`, `table_counts`, `top_gainers`, `top_losers`,
`volume_leaders`, `delivery_spike`, `fo_most_traded`, `fo_open_interest`,
`index_history`, `delivery_ratio`.

## `bhavkit export`

Export a table to parquet or CSV with optional filters. Writes to `--out`
(file or directory); defaults to `<data_dir>/exports/`.

```
Usage: bhavkit export [OPTIONS]

Options:
  *  --table      <str>  Table to export (bhav_daily, index_daily, fo_daily,
                         deliverable_daily, equity_master). [required]
     --symbols    <str>  Comma-separated symbol filter.
     --indexes    <str>  Comma-separated index filter.
     --series     <str>  Series filter (bhav_daily).
     --start      <str>  Start date filter (YYYY-MM-DD).
     --end        <str>  End date filter (YYYY-MM-DD).
     --format     <str>  parquet | csv. [default: parquet]
     --out        <str>  Output file or directory.
     --config     <str>  Path to TOML config file.
     --db-path    <str>  DuckDB database path.
     --data-dir   <str>  Cache/download directory.
     --help              Show this message and exit.
```

## `bhavkit config`

Show and edit the TOML configuration file. `bhavkit init` auto-creates a
default `bhavkit.toml` on first run, so no manual copy is needed; use these
commands to inspect or tweak it. Edits preserve comments and apply immediately
to subsequent commands.

```
Usage: bhavkit config [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  show   Show the effective (resolved) configuration.
  set    Update one setting in the config file.
  unset  Remove a setting from the config file.
  path   Print the config file that edits would target.
  keys   List all valid setting names.
```

### `config show`

```
Usage: bhavkit config show [OPTIONS]

Options:
  --config  <str>  Path to TOML config file.
  --help           Show this message and exit.
```

Prints every resolved setting (defaults + file + `BHAV_*` env overlays) plus
the config file path. CLI flags still override whatever is shown.

### `config set <key> <value>`

Update one setting, e.g.:

```
bhavkit config set concurrency 8
bhavkit config set source local
bhavkit config set backoff_base 0.5
```

Values are validated and coerced (numbers, booleans, paths) by the pydantic
config model; unknown keys or invalid values (e.g. `source = nse2`) exit 2.

### `config unset <key>`

Remove a setting so it falls back to its built-in default.

### `config path`

Print the file that `set`/`unset` would edit (first existing config file:
`bhavkit.toml`, else `~/.config/bhavkit/config.toml`).

### `config keys`

List all valid setting names.

---

## `bhavkit holidays`

Show the advisory NSE holiday calendar used for gap reporting. The NSE server
(404 on a weekday) remains the authoritative non-trading-day signal.

```
Usage: bhavkit holidays [OPTIONS]

Options:
  --years  <str>   Comma-separated years. [default: 2024,2025,2026]
  --help           Show this message and exit.
```