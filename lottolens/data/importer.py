"""CSV import (seed file and user uploads)."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database, UpsertStats
from .validate import Draw, DrawValidationError, make_draw

log = logging.getLogger("lottolens.import")

REQUIRED = ["draw_date", "n1", "n2", "n3", "n4", "n5", "n6"]


@dataclass
class ImportReport:
    rows: int = 0
    stats: UpsertStats = field(default_factory=UpsertStats)
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        msg = f"{self.rows} rows read: {self.stats}"
        if self.errors:
            msg += f"; {len(self.errors)} rejected"
        return msg


def parse_csv(text: str, source: str) -> tuple[list[Draw], list[str]]:
    """Parse CSV text. Accepts optional columns draw_number, supp1, supp2."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return [], ["file is empty"]
    cols = [c.strip().lower() for c in reader.fieldnames]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        return [], [f"missing required column(s): {', '.join(missing)}"]
    draws, errors = [], []
    for lineno, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        try:
            supps = [row["supp1"], row["supp2"]] if row.get("supp1") and row.get("supp2") else None
            draws.append(
                make_draw(
                    row["draw_date"],
                    [row[f"n{i}"] for i in range(1, 7)],
                    supps,
                    draw_number=row.get("draw_number") or None,
                    source=source,
                )
            )
        except DrawValidationError as exc:
            errors.append(f"line {lineno}: {exc}")
    seen: set[str] = set()
    for d in draws:
        if d.key in seen:
            errors.append(f"duplicate draw date {d.key} in file")
        seen.add(d.key)
    return draws, errors


def import_csv_text(db: Database, text: str, source: str = "csv") -> ImportReport:
    draws, errors = parse_csv(text, source)
    report = ImportReport(rows=len(draws) + len(errors), errors=errors)
    if draws:
        report.stats = db.upsert_draws(draws)
    log.info("CSV import (%s): %s", source, report)
    return report


def import_csv_file(db: Database, path: Path | str, source: str = "csv") -> ImportReport:
    return import_csv_text(db, Path(path).read_text(encoding="utf-8"), source)


def ensure_seeded(db: Database, seed: Path) -> ImportReport | None:
    """Import the seed CSV on first run (empty database)."""
    if db.draw_count() > 0 or not seed.exists():
        return None
    return import_csv_file(db, seed, source="seed-csv")
