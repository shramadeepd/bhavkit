from __future__ import annotations

from datetime import date

from bhavkit.calendar import (
    NSE_HOLIDAYS,
    is_business_day,
    trading_day_candidates,
    weekdays,
)


def test_weekend_is_not_business_day():
    assert not is_business_day(date(2024, 1, 6))  # Saturday
    assert not is_business_day(date(2024, 1, 7))  # Sunday


def test_known_holiday_is_not_business_day():
    assert (1, 26) in NSE_HOLIDAYS[2024]
    assert not is_business_day(date(2024, 1, 26))  # Republic Day 2024
    assert not is_business_day(date(2024, 3, 25))  # Holi 2024


def test_regular_trading_day():
    assert is_business_day(date(2024, 1, 3))  # Wednesday


def test_candidate_count_jan2024():
    days = trading_day_candidates(date(2024, 1, 1), date(2024, 1, 31))
    # 23 weekdays minus 2 holidays (Jan 22 Ram Mandir, Jan 26 Republic Day) = 21
    assert len(days) == 21
    assert date(2024, 1, 22) not in days  # trading holiday discovered by report
    assert date(2024, 1, 26) not in days
    assert date(2024, 1, 27) not in days
    assert date(2024, 1, 28) not in days
    assert date(2024, 1, 1) in days  # New Year 2024 was a trading day


def test_weekdays_helper():
    days = weekdays(date(2024, 1, 1), date(2024, 1, 7))
    assert len(days) == 5


def test_unknown_year_has_no_advisory_holidays():
    assert is_business_day(date(1995, 1, 26))