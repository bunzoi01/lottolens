"""Draw-date rules, in Australia/Sydney time (DST-aware via zoneinfo).

Saturday Lotto is drawn every Saturday night. The one exception seen in the
historical record: when 1 January falls on a Saturday, the draw moves to
Friday 31 December (1999, 2004, 2010, 2021). Once (1994) the draw stayed on
Saturday 1 January, so validation accepts both; scheduling follows the recent
practice of moving the draw to the Friday.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")

# Results are normally published by about 8:30pm. Treat a draw as "happened"
# from 9pm Sydney time on draw night.
RESULTS_AVAILABLE = time(21, 0)


def now_sydney() -> datetime:
    return datetime.now(SYDNEY)


def _new_years_eve_shift(saturday: date) -> date:
    """Return the actual draw date for the draw scheduled on this Saturday."""
    if saturday.month == 1 and saturday.day == 1:
        return saturday - timedelta(days=1)
    return saturday


def is_valid_draw_date(d: date) -> bool:
    if d.weekday() == 5:  # Saturday
        return True
    if d.month == 1 and d.day == 1:
        return True
    # Friday 31 Dec when 1 Jan is a Saturday
    return d.month == 12 and d.day == 31 and d.weekday() == 4


def draw_dates_between(start: date, end: date) -> list[date]:
    """Scheduled draw dates in [start, end], applying the New Year's Eve rule."""
    out: list[date] = []
    sat = start + timedelta(days=(5 - start.weekday()) % 7)
    # A Friday 31 Dec draw replaces the following Saturday, so look one day ahead.
    if start.month == 12 and start.day == 31 and start.weekday() == 4:
        sat = start + timedelta(days=1)
    while True:
        actual = _new_years_eve_shift(sat)
        if actual > end:
            break
        if actual >= start:
            out.append(actual)
        sat += timedelta(days=7)
    return out


def next_draw_after(d: date) -> date:
    """The first scheduled draw strictly after date d."""
    sat = d + timedelta(days=1)
    sat += timedelta(days=(5 - sat.weekday()) % 7)
    actual = _new_years_eve_shift(sat)
    if actual <= d:  # d was itself the shifted Friday draw
        actual = _new_years_eve_shift(sat + timedelta(days=7))
    return actual


def draw_results_time(d: date) -> datetime:
    return datetime.combine(d, RESULTS_AVAILABLE, tzinfo=SYDNEY)


def most_recent_draw_date(now: datetime | None = None) -> date:
    """The latest draw whose results should be available by `now`."""
    now = (now or now_sydney()).astimezone(SYDNEY)
    candidate = next_draw_after(now.date() - timedelta(days=8))
    latest = candidate
    while candidate <= now.date():
        if draw_results_time(candidate) <= now:
            latest = candidate
        candidate = next_draw_after(candidate)
    return latest


def upcoming_draw_date(now: datetime | None = None) -> date:
    """The next draw whose results are not yet available."""
    return next_draw_after(most_recent_draw_date(now))
