from __future__ import annotations

from datetime import date, timedelta

# Advisory NSE equity-market holidays (best-effort). The server 404 on a
# candidate day is treated as authoritative: a missing file for a weekday is
# logged as a non-trading day regardless of this table. Keep this list updated
# for gap reporting; backfills remain correct without it.
NSE_HOLIDAYS: dict[int, set[tuple[int, int]]] = {
    2023: {
        (1, 26), (3, 7), (3, 30), (4, 4), (4, 7), (4, 14), (5, 1), (6, 28),
        (8, 15), (9, 18), (10, 24), (11, 27), (12, 25),
    },
    2024: {
        (1, 22), (1, 26), (3, 8), (3, 25), (3, 29), (4, 11), (5, 1), (6, 17),
        (7, 8), (8, 15), (10, 2), (11, 1), (11, 15), (12, 25),
    },
    2025: {
        (2, 26), (3, 14), (3, 31), (4, 10), (4, 14), (4, 18), (5, 1), (5, 12),
        (8, 15), (8, 27), (10, 2), (10, 21), (11, 5), (12, 25),
    },
    # 2026 — advisory only until the official list is confirmed.
    2026: {
        (2, 17), (3, 4), (4, 1), (4, 3), (5, 1), (8, 15), (10, 2), (11, 9),
        (12, 25),
    },
}


def is_nse_holiday(day: date) -> bool:
    return (day.month, day.day) in NSE_HOLIDAYS.get(day.year, set())


def is_business_day(day: date) -> bool:
    """True for weekdays that are not (advisory) NSE holidays."""
    return day.weekday() < 5 and not is_nse_holiday(day)


def trading_day_candidates(start: date, end: date) -> list[date]:
    """All plausible trading days in [start, end] (weekdays minus advisory
    holidays). Missing files for candidates are logged as non-trading days."""
    days: list[date] = []
    day = start
    while day <= end:
        if is_business_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def weekdays(start: date, end: date) -> list[date]:
    """All weekdays in [start, end] (used for raw coverage checks)."""
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days