from __future__ import annotations

import logging
from datetime import date

LOGGER_NAME = "bhavkit"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of calendar dates from start to end."""
    step = (end - start).days
    if step < 0:
        raise ValueError(f"end ({end}) must be on or after start ({start})")
    return [start.fromordinal(start.toordinal() + i) for i in range(step + 1)]


def parse_flexible_date(value: str) -> date:
    """Parse an ISO date (YYYY-MM-DD). Raises ValueError on malformed input."""
    from datetime import datetime

    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"invalid date {value!r}; expected ISO format YYYY-MM-DD"
        ) from exc


def iso8601(d: date) -> str:
    return d.isoformat()