# bhavkit

**Download, clean, and store historical NSE bhavcopy data in a local DuckDB database.**

`bhavkit` is a typed Python CLI and library that turns the National Stock
Exchange's raw bhavcopy archives into a queryable, validated, analytics-ready
dataset. It handles the fiddly parts of working with NSE data — archive
downloading, format normalization, validation, deduplication, and gap tracking —
so you can spend your time analyzing markets instead of wrestling with files.
---

## Features

- **Four NSE datasets** — CM (equity bhavcopy), IDX (index values), FO
  (futures & options), DELIV (deliverable positions) — plus the equity master
  (symbol metadata), normalized into a versioned schema.
- **Reliable ingestion** — asynchronous downloads with retries, exponential
  backoff + jitter, polite rate limiting, a resumable on-disk cache, and
  idempotent `INSERT OR REPLACE` upserts keyed on `sha256`. Re-running a range
  is a no-op.
- **Built-in data-quality tooling** — monthly coverage reports (Markdown +
  JSON), gap detection, anomaly flags (extreme moves, invalid OHLC, delivery
  mismatches), equity-master drift, and cross-dataset coverage.
- **Query everything** — a read-only interactive SQL shell with template
  queries, plus parquet/CSV export with symbol/date filters.
- **Offline mode** — run the entire pipeline against a local mirror of
  pre-downloaded files (`source = "local"`), no NSE dependency.
- **Configuration that configures itself** — `bhavkit init` creates the
  database and a default `bhavkit.toml` with zero manual setup; tune via a TOML
  file, `BHAV_*` env vars, CLI flags, or the `bhavkit config` command.

### Built with

[Python ≥ 3.11](https://www.python.org) · [Typer](https://typer.tiangolo.com) ·
[DuckDB](https://duckdb.org) · [Polars](https://pola.rs) ·
[httpx](https://www.python-httpx.org) · [pydantic](https://docs.pydantic.dev) ·
[Rich](https://rich.readthedocs.io)

---

## Table of contents

- [Requirements](#requirements)
- [Installation](#installation)
  - [As a CLI](#as-a-cli)
  - [From a GitHub clone](#from-a-github-clone)
  - [As a Python library](#as-a-python-library)
- [Quickstart](#quickstart)
- [Usage](#usage)
- [Configuration](#configuration)
- [Data model](#data-model)
- [Library usage](#library-usage)
- [Reliability & design notes](#reliability--design-notes)
- [Development](#development)
- [Documentation](#documentation)
- [License](#license)

---

## Requirements

- Python **3.11+**
- ~1 GB disk for a multi-year dataset (a decade of daily CM data is roughly
  a few hundred MB compressed in DuckDB)

## Installation

### As a CLI

```bash
# global CLI via uv — from a checkout, a wheel, or a git URL
uv tool install .                                  # local checkout / wheel
uv tool install "bhavkit @ git+https://github.com/<you>/bhavkit"  # from GitHub

# ephemeral run, no install
uvx --from . bhavkit --help

# or a classic pip install (Python 3.11+)
pip install .
pip install git+https://github.com/<you>/bhavkit
```

This puts a `bhavkit` executable on your path:

```bash
bhavkit --help
bhavkit init
bhavkit update --start 2024-01-01 --end 2024-01-31
```

### From a GitHub clone

```bash
git clone https://github.com/<you>/bhavkit.git
cd bhavkit
uv sync                            # or: pip install .
uv run bhavkit --help
```

### As a Python library

`bhavkit` is a regular package — add it to any project and `import bhavkit`:

```bash
uv add --editable ../bhavkit                        # local checkout
uv add "bhavkit @ git+https://github.com/<you>/bhavkit"   # from GitHub
# (once published): uv add bhavkit
```

---

## Quickstart

```bash
# 1. create the database, schema, and a default config — nothing to configure
bhavkit init

# 2. sanity-check the NSE archive endpoints
bhavkit probe

# 3. pull a month of data across all datasets
bhavkit update --start 2024-01-01 --end 2024-01-31 --datasets cm,idx,fo,deliv

# 4. refresh the equity master, then run a coverage / quality report
bhavkit master refresh
bhavkit report --month 2024-01

# 5. query the result
bhavkit query --template top_gainers
```

Your data now lives in `bhavkit.duckdb` (`data/` holds the file cache and
report output). Wait for the market close (~15:45 IST) to see the day's data,
then `bhavkit update` for an incremental refresh.

---

## Usage

| Command | What it does |
|---|---|
| `bhavkit init` | Create the DB, schema, migration records, cache dirs, and a default `bhavkit.toml`. |
| `bhavkit probe` | Test the configured NSE base URLs and report reachability. |
| `bhavkit update` | Download + ingest a date range (default: last 7 days). |
| `bhavkit backfill --start <date>` | Same engine as `update`, sized for large historical ranges; resumable via the cache. |
| `bhavkit master refresh` | Refresh the equity master from `EQUITY_L.csv`. |
| `bhavkit status` | Bar/master/gap counts + a coverage-by-month table from `ingest_log`. |
| `bhavkit report` | Data-quality report (`report_<product>.md` + `.json`); refreshes `data_gaps`. |
| `bhavkit query` | Read-only interactive SQL shell; one-shot with `--sql` / `--template`. |
| `bhavkit export` | Export a table to parquet or CSV with symbol/date filters. |
| `bhavkit holidays` | Show the advisory NSE holiday calendar. |
| `bhavkit config` | Inspect/edit the config file: `show`, `set <key> <value>`, `unset`, `path`, `keys`. |

Every command accepts `--config <path>`, `--db-path <path>`, and
`--data-dir <path>` to override configuration. A full reference with every flag
is in [`docs/cli.md`](./docs/cli.md).

**Updating.** `update` / `backfill` share one engine:

```
--start, --end   date range (YYYY-MM-DD)
--datasets       comma-separated: cm, idx, fo, deliv   (default: cm)
--source         nse | local                           (default: nse)
--local-dir      mirror folder when --source local
--nse-base-url   override the archive base URL
--force          re-ingest even if already ingested
```

**Querying.** `bhavkit query` is a read-only shell (write statements are
blocked). In the shell: `\q` `\h` `\d` `\t` `\r <name>`, or run any read query
ending in `;`. Built-in templates: `latest`, `table_counts`, `top_gainers`,
`top_losers`, `volume_leaders`, `delivery_spike`, `fo_most_traded`,
`fo_open_interest`, `index_history`, `delivery_ratio`.

```bash
bhavkit query --template top_gainers          # most recent day, top 10 by % change
bhavkit query --sql "SELECT * FROM bhav_daily WHERE symbol='SBIN' LIMIT 5"
```

**Exporting.**

```bash
bhavkit export --table bhav_daily --symbols SBIN,RELIANCE --format csv --out sb.csv
bhavkit export --table fo_daily --start 2024-01-01 --end 2024-01-05 --format parquet
bhavkit export --table index_daily --indexes "Nifty 50" --format csv
```

Tables: `bhav_daily`, `index_daily`, `fo_daily`, `deliverable_daily`,
`equity_master`. Output defaults to `data/exports/` with a descriptive filename.

---

## Configuration

Precedence, highest wins: **CLI flags > `BHAV_*` env vars > TOML file >
defaults**.

`bhavkit init` writes a default `bhavkit.toml` automatically, and TOML is read
from `bhavkit.toml` in the project root (falling back to
`~/.config/bhavkit/config.toml`). There is nothing to copy by hand — edit the
file or use `bhavkit config set`.

```bash
bhavkit config show                    # resolved settings (defaults + file + env)
bhavkit config set concurrency 8
bhavkit config set source local        # switch to an offline mirror
bhavkit config unset source            # revert to default
```

| Key | Default | Description |
|---|---|---|
| `db_path` | `bhavkit.duckdb` | DuckDB database file. |
| `data_dir` | `data` | Cache, report, and export output root. |
| `source` | `nse` | `nse` (live archive) or `local` (offline mirror). |
| `nse_base_url` | `https://nsearchives.nseindia.com` | NSE archive root. |
| `local_dir` | — | Mirror root when `source = "local"`. |
| `concurrency` | `4` | Max parallel downloads (1–32). |
| `retries` | `5` | Retries for 408/429/5xx, beyond the first attempt. |
| `backoff_base` | `1.0` | Exponential backoff base (seconds) + jitter. |
| `rate_limit_sleep` | `0.35` | Minimum interval between requests. |
| `timeout` | `30.0` | Per-request timeout (seconds). |
| `user_agent` | browsersish `Mozilla/5.0 … bhavkit/0.1` | HTTP User-Agent. |
| `verbose` | `false` | Debug logging. |

Env vars use the dot-flattened form: `BHAV_CONCURRENCY=8`,
`BHAV_NSE_BASE_URL=https://…`, `BHAV_SOURCE=local`. A fully commented sample
lives at [`bhavkit.toml.example`](./bhavkit.toml.example).

**Sources.** `nse` resolves against `nsearchives.nseindia.com` (alternate
mirrors are probed by `bhavkit probe`):

- `cm`: `content/historical/EQUITIES/<YYYY>/<MON>/cmDDMONYYYYbhav.csv.zip`
- `idx`: `content/indices/ind_close_all_DDMMYYYY.csv`
- `fo`: `content/historical/DERIVATIVES/<YYYY>/<MON>/foDDMONYYYYbhav.csv.zip`
- `deliv`: `products/content/sec_bhavdata_full_DDMMYYYY.csv`

`local` reads an offline mirror laid out as
`<local_dir>/<product>/<YYYY>/<MMM>/<filename>` (same filenames as NSE), which
lets you run the full pipeline against pre-downloaded files.

> NSE can rate-limit bulk scraping — keep `rate_limit_sleep >= 0.3` and prefer
> incremental `update` for daily refreshes.

---

## Data model

The schema is versioned via `schema_migrations`; `bhavkit init` migrates older
databases in place.

| Table | Primary key | Notes |
|---|---|---|
| `bhav_daily` | `(symbol, series, date)` | OHLC, prev_close, last, turnover (INR), traded qty, trades, delivery qty/%. |
| `index_daily` | `(index_name, date)` | Daily index OHLC, volume, turnover. |
| `fo_daily` | `(symbol, instrument, expiry_date, option_type, strike_price, date)` | F&O; settle_price, contracts, value, open_interest, change_in_oi. |
| `deliverable_daily` | `(symbol, series, date)` | Traded vs delivered quantity, delivery-to-traded ratio. |
| `equity_master` | `(symbol, series)` | Name, ISIN, industry, status from `EQUITY_L.csv`. |
| `ingest_log` | auto | Audit: product, date, url, sha256, rows, status, error, duration. |
| `qc_issues` | auto | Per-file validation findings (bad dates, empties, OHLC violations…). |
| `data_gaps` | `(product, date, gap_type)` | Derived from the latest report. |

Notes: current NSE bhavcopies omit `AVG_PRICE` (stored `NULL`); F&O zero OHLC
is legitimate for illiquid strikes; both the classic (`DELIV`/`LACS`) and
current (`ISIN`/`TIMESTAMP`) CM formats are normalized to the same schema with
turnover always in rupees.

---

## Library usage

Fine-grained control does not require the CLI — everything is a plain Python
API:

```python
from pathlib import Path

from bhavkit.config import load_config
from bhavkit.db import Database
from bhavkit.query import run_sql, execute_template

cfg = load_config()
db = Database(cfg.db_path)
db.bootstrap()                                # idempotent schema setup

df = run_sql(db, "SELECT symbol, close FROM bhav_daily WHERE date = '2024-01-05' ORDER BY close DESC LIMIT 5")
print(df)

runners = execute_template(db, "top_gainers")  # returns a polars DataFrame
db.close()
```

See the executable **workbook** for the complete walkthrough — bootstrap,
the ingest pipeline (`read_bhav_file` → `clean_bars` → `upsert_bars`), template
queries, reports, parquet export, and driving the CLI as a module:

```bash
uv sync
uv run --with jupyter --with ipykernel \
    jupyter nbconvert --to notebook --execute --inplace workbook/bhavkit.ipynb
```

> Records a single-writer DuckDB database: only one process may hold the file
> open at a time — close any open connection before shelling out to the CLI.

---

## Reliability & design notes

- **Resumable by design.** Files are cached on disk keyed by their URL; ingest
  is idempotent and skipped when the `sha256` is unchanged. An interrupted
  `backfill` resumes on the next run instead of restarting.
- **Non-trading days.** A weekday that returns `404` from NSE is logged as
  `not_a_trading_day` — the server is the authority, not the advisory calendar
  (which is used only for reporting). Zero-error, resumable backfills make
  reporting's gap table accurate.
- **Polite by default.** Rate-limited requests, exponential backoff with jitter
  on `408`/`429`/`5xx`, and cleanup of partial files on failure.
- **Validation with context.** Extreme single-day moves are usually corporate
  actions (split/bonus), not bad data — the DQ report flags them rather than
  hiding them. ETFs trade as `EQ` but aren't in the equity master, so they
  surface as "master drift" for you to judge.

---

## Development

```bash
uv sync --extra dev

uv run pytest       # test suite (81 tests)
uv run ruff check . # lint
uv run mypy src     # typecheck
```

The implementation tree lives under `src/bhavkit/` — `cli.py` (commands),
`config.py` (pydantic + precedence), `db.py` + `schema.sql` (DuckDB, versioned),
`sources/` (nse/local), `download.py` (async pool + cache), `ingest.py`
(per-product pipelines), `clean.py` (validation), `report.py` (DQ reports),
`query.py` (SQL shell + templates), `export.py`, `metadata.py`, `calendar.py`.

---

## Documentation

- **CLI reference** — every command and flag: [`docs/cli.md`](./docs/cli.md)
- **Library walkthrough** — [`workbook/bhavkit.ipynb`](./workbook/bhavkit.ipynb)
- **Roadmap & design notes** — [`plan.md`](./plan.md)

---

## License

Released under the [MIT License](./LICENSE).