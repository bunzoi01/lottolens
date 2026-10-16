"""Fetch new draws and back-fill missing ones."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from ..data.dates import most_recent_draw_date, next_draw_after
from ..data.db import Database, UpsertStats
from .base import ResultsProvider
from .http import FetchError

log = logging.getLogger("lottolens.fetch")


@dataclass
class RefreshReport:
    stats: UpsertStats = field(default_factory=UpsertStats)
    years: list[int] = field(default_factory=list)
    new_dates: list[date] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    up_to_date: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def is_stale(db: Database, now: datetime | None = None) -> bool:
    latest = db.latest_draw_date()
    return latest is None or latest < most_recent_draw_date(now)


def refresh(
    db: Database,
    provider: ResultsProvider,
    *,
    full: bool = False,
    now: datetime | None = None,
) -> RefreshReport:
    """Back-fill every draw after the latest stored one.

    full=True walks every yearly archive from 1986 instead, to enrich existing
    rows with supps and draw numbers and to cross-check the stored numbers.
    Past-year pages are cached forever, so this costs one request per year once.
    """
    report = RefreshReport()
    latest = db.latest_draw_date()
    target = most_recent_draw_date(now)
    if not full and latest is not None and latest >= target:
        report.up_to_date = True
        db.log(f"Up to date: latest stored draw {latest}, most recent draw {target}.")
        return report

    first_year = 1986 if (full or latest is None) else next_draw_after(latest).year
    report.years = list(range(first_year, target.year + 1))
    known = {d for d in db.draws_df()["draw_date"]} if latest else set()

    for year in report.years:
        try:
            draws = provider.fetch_year(year)
        except FetchError as exc:
            msg = f"{provider.name}: {year} archive failed: {exc}"
            log.warning(msg)
            db.log(msg, "ERROR")
            report.errors.append(msg)
            # Robots disallow or offline: stop instead of hammering the site.
            break
        if not full:
            draws = [d for d in draws if d.draw_date not in known]
        stats = db.upsert_draws(draws)
        report.stats += stats
        report.new_dates += [d.draw_date for d in draws if d.draw_date not in known]
        db.log(f"{provider.name}: {year} archive: {len(draws)} draws parsed ({stats}).")

    # The front page can show a fresh result before the archive updates.
    if not report.errors and (db.latest_draw_date() or date.min) < target:
        try:
            latest_draws = [d for d in provider.fetch_latest() if d.draw_date not in known]
            stats = db.upsert_draws(latest_draws)
            report.stats += stats
            report.new_dates += [d.draw_date for d in latest_draws if d.draw_date not in report.new_dates]
            db.log(f"{provider.name}: latest page: {stats}.")
        except FetchError as exc:
            report.errors.append(str(exc))
            db.log(str(exc), "ERROR")

    report.new_dates = sorted(set(report.new_dates))
    now_latest = db.latest_draw_date()
    if now_latest is not None and now_latest < target and not report.errors:
        db.log(f"Source does not have the {target} draw yet (latest available {now_latest}).", "WARNING")
    disc = db.discrepancies()
    if disc:
        db.log(f"{len(disc)} unresolved source disagreement(s) need review on the History page.", "WARNING")
    log.info("refresh: %s; new draws: %s", report.stats, [str(d) for d in report.new_dates])
    return report
