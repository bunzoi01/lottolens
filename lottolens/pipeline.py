"""The refresh pipeline shared by the CLI, the web app and the scheduled job.

fetch new draws -> score stored suggestions against them -> generate next week's set
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date

from . import paths
from .algorithm.store import weekly_set
from .backtest.tracking import score_pending
from .config import load_settings
from .data.db import Database
from .data.importer import ensure_seeded
from .fetch.http import PoliteClient
from .fetch.lottonumbers import LottoNumbersProvider
from .fetch.service import refresh as fetch_refresh

log = logging.getLogger("lottolens.pipeline")

_refresh_lock = threading.Lock()


@dataclass
class PipelineReport:
    new_draws: list[date] = field(default_factory=list)
    scored: int = 0
    target: date | None = None
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None

    def summary(self) -> str:
        if self.skipped:
            return self.skipped
        parts = [f"{len(self.new_draws)} new draw(s)"]
        if self.scored:
            parts.append(f"{self.scored} stored suggestion(s) scored")
        if self.target:
            parts.append(f"suggestions ready for {self.target:%a %d %b %Y}")
        if self.errors:
            parts.append(f"errors: {'; '.join(self.errors)}")
        return ", ".join(parts)


def init_db(db: Database | None = None) -> Database:
    db = db or Database()
    report = ensure_seeded(db, paths.SEED_CSV)
    if report:
        db.log(f"Seed CSV imported: {report}")
    return db


def run_refresh(db: Database, *, full: bool = False, fetch: bool = True) -> PipelineReport:
    rep = PipelineReport()
    if not _refresh_lock.acquire(blocking=False):
        rep.skipped = "A refresh is already running."
        return rep
    try:
        settings = load_settings(db)
        if fetch and settings.lottonumbers_enabled:
            # First run walks every yearly archive once, to add supps and draw
            # numbers to the seed CSV rows and cross-check them.
            full = full or not db.kv_get("full_backfill_done", False)
            client = PoliteClient()
            try:
                fr = fetch_refresh(db, LottoNumbersProvider(client), full=full)
            finally:
                client.close()
            rep.new_draws = fr.new_dates
            rep.errors = fr.errors
            if full and fr.ok:
                db.kv_set("full_backfill_done", True)
        elif fetch:
            db.log("Automatic fetching is turned off in Settings.", "WARNING")
        rep.scored = score_pending(db)
        s = weekly_set(db, settings)
        rep.target = s.target_draw_date if s else None
        db.log(f"Refresh finished: {rep.summary()}")
        log.info("pipeline: %s", rep.summary())
        return rep
    except Exception as exc:  # keep the app alive; the log has the details
        log.exception("refresh failed")
        db.log(f"Refresh failed: {exc}", "ERROR")
        rep.errors.append(str(exc))
        return rep
    finally:
        _refresh_lock.release()


def refresh_running() -> bool:
    return _refresh_lock.locked()
