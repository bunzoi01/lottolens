from datetime import date, datetime

from lottolens.data.dates import (
    SYDNEY,
    draw_dates_between,
    is_valid_draw_date,
    most_recent_draw_date,
    next_draw_after,
    upcoming_draw_date,
)


def test_valid_draw_dates():
    assert is_valid_draw_date(date(2026, 10, 10))  # Saturday
    assert not is_valid_draw_date(date(2026, 10, 11))  # Sunday
    assert is_valid_draw_date(date(2021, 12, 31))  # Fri 31 Dec, 1 Jan 2022 is a Saturday
    assert not is_valid_draw_date(date(2026, 12, 31))  # Thursday, 1 Jan 2027 is a Friday
    assert is_valid_draw_date(date(2027, 1, 1))  # New Year's Day exception from the brief


def test_next_draw_after_handles_new_years_eve_shift():
    assert next_draw_after(date(2026, 10, 10)) == date(2026, 10, 17)
    assert next_draw_after(date(2026, 10, 14)) == date(2026, 10, 17)
    # 1 Jan 2028 is a Saturday -> draw moves to Fri 31 Dec 2027
    assert next_draw_after(date(2027, 12, 25)) == date(2027, 12, 31)
    assert next_draw_after(date(2027, 12, 31)) == date(2028, 1, 8)
    assert next_draw_after(date(2021, 12, 25)) == date(2021, 12, 31)


def test_draw_dates_between_matches_history_gaps():
    dates = draw_dates_between(date(2021, 12, 1), date(2022, 1, 20))
    assert dates == [
        date(2021, 12, 4), date(2021, 12, 11), date(2021, 12, 18), date(2021, 12, 25),
        date(2021, 12, 31), date(2022, 1, 8), date(2022, 1, 15),
    ]


def test_most_recent_draw_respects_results_time():
    # Saturday 6pm Sydney: tonight's results not out yet
    assert most_recent_draw_date(datetime(2026, 10, 17, 18, 0, tzinfo=SYDNEY)) == date(2026, 10, 10)
    # Saturday 9:30pm Sydney: results out
    assert most_recent_draw_date(datetime(2026, 10, 17, 21, 30, tzinfo=SYDNEY)) == date(2026, 10, 17)
    assert upcoming_draw_date(datetime(2026, 10, 16, 12, 0, tzinfo=SYDNEY)) == date(2026, 10, 17)


def test_timezone_conversion_from_utc():
    from zoneinfo import ZoneInfo

    utc = ZoneInfo("UTC")
    # 17 Oct 2026 10:30 UTC = 21:30 AEDT (UTC+11, daylight saving) -> results out
    assert most_recent_draw_date(datetime(2026, 10, 17, 10, 30, tzinfo=utc)) == date(2026, 10, 17)
    # 4 Jul 2026 10:30 UTC = 20:30 AEST (UTC+10, no DST) -> not yet
    assert most_recent_draw_date(datetime(2026, 7, 4, 10, 30, tzinfo=utc)) == date(2026, 6, 27)
