"""Decide whether the hourly launchd job should do anything.

launchd fires hourly in the Mac's local time zone. The real schedule is
Sunday 10:00 Australia/Sydney with a Monday 10:00 retry, applied here in
Python so it is DST-aware and correct whatever time zone the Mac is set to.
At most one attempt is made per window.
"""

from __future__ import annotations

from datetime import datetime

from ..data.dates import SYDNEY, now_sydney
from ..data.db import Database
from ..fetch.service import is_stale

RUN_HOUR = 10
WINDOWS = {6: "Sunday", 0: "Monday"}  # datetime.weekday()


def should_run_scheduled(db: Database, now: datetime | None = None) -> tuple[bool, str]:
    now = (now or now_sydney()).astimezone(SYDNEY)
    if not is_stale(db, now):
        return False, "results are up to date"
    if now.weekday() not in WINDOWS or now.hour < RUN_HOUR:
        return False, "outside the Sunday/Monday 10:00 Sydney windows"
    key = f"scheduled_attempt:{now.date().isoformat()}"
    if db.kv_get(key):
        return False, f"already tried this {WINDOWS[now.weekday()]}"
    db.kv_set(key, now.isoformat())
    return True, f"{WINDOWS[now.weekday()]} window"
