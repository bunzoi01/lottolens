"""SQLite storage. All writes are idempotent upserts.

Merging rule for draws: a draw is keyed by its date. If a second source supplies
the same winning numbers, missing fields (draw number, supps) are filled in and
the source list is extended. If a source disagrees on the winning numbers or
supps, the stored row is left untouched and a discrepancy is recorded for the UI.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .. import paths
from .validate import Draw

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    draw_date   TEXT PRIMARY KEY,
    draw_number INTEGER NULL,
    n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
    n4 INTEGER NOT NULL, n5 INTEGER NOT NULL, n6 INTEGER NOT NULL,
    supp1 INTEGER NULL, supp2 INTEGER NULL,
    source      TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discrepancies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_date   TEXT NOT NULL,
    field       TEXT NOT NULL,
    stored      TEXT NOT NULL,
    stored_source TEXT NOT NULL,
    incoming    TEXT NOT NULL,
    incoming_source TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (draw_date, field, incoming, incoming_source)
);
CREATE TABLE IF NOT EXISTS suggestions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    target_draw_date TEXT NOT NULL,
    kind          TEXT NOT NULL,         -- 'weekly' (deterministic) or 'regenerate'
    seed          INTEGER NOT NULL,
    rank          INTEGER NOT NULL,
    numbers       TEXT NOT NULL,         -- comma-separated, sorted
    score         REAL NOT NULL,
    explanation   TEXT NOT NULL,
    params_hash   TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    data_through  TEXT NOT NULL,         -- latest draw date used
    algo_version  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (target_draw_date, kind, seed, params_hash, rank)
);
CREATE TABLE IF NOT EXISTS suggestion_results (
    suggestion_id INTEGER PRIMARY KEY REFERENCES suggestions(id),
    draw_date     TEXT NOT NULL,
    matches       INTEGER NOT NULL,
    supp_matches  INTEGER NULL,
    division      INTEGER NULL,
    scored_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class UpsertStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0

    def __iadd__(self, other: "UpsertStats") -> "UpsertStats":
        self.inserted += other.inserted
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.conflicts += other.conflicts
        return self

    def __str__(self) -> str:
        return (
            f"{self.inserted} new, {self.updated} enriched, "
            f"{self.unchanged} unchanged, {self.conflicts} conflicts"
        )


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else paths.db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------- draws
    def upsert_draws(self, draws: Iterable[Draw]) -> UpsertStats:
        stats = UpsertStats()
        now = utcnow()
        with self.connect() as conn:
            for d in draws:
                stats += self._upsert_one(conn, d, now)
        return stats

    def _upsert_one(self, conn: sqlite3.Connection, d: Draw, now: str) -> UpsertStats:
        row = conn.execute("SELECT * FROM draws WHERE draw_date = ?", (d.key,)).fetchone()
        nums = list(d.numbers)
        if row is None:
            supps = list(d.supps) if d.supps else [None, None]
            conn.execute(
                "INSERT INTO draws VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (d.key, d.draw_number, *nums, *supps, d.source, now),
            )
            return UpsertStats(inserted=1)

        stored_nums = [row[f"n{i}"] for i in range(1, 7)]
        sources = row["source"].split("+")
        conflict = False
        if stored_nums != nums:
            self._record_discrepancy(conn, d.key, "numbers", stored_nums, row["source"], nums, d.source, now)
            conflict = True
        stored_supps = [row["supp1"], row["supp2"]]
        if d.supps and stored_supps[0] is not None and sorted(stored_supps) != sorted(d.supps):
            self._record_discrepancy(conn, d.key, "supps", stored_supps, row["source"], list(d.supps), d.source, now)
            conflict = True
        if (
            d.draw_number is not None
            and row["draw_number"] is not None
            and row["draw_number"] != d.draw_number
        ):
            self._record_discrepancy(
                conn, d.key, "draw_number", [row["draw_number"]], row["source"], [d.draw_number], d.source, now
            )
            conflict = True
        if conflict:
            return UpsertStats(conflicts=1)

        updates: dict[str, object] = {}
        if row["draw_number"] is None and d.draw_number is not None:
            updates["draw_number"] = d.draw_number
        if stored_supps[0] is None and d.supps:
            updates["supp1"], updates["supp2"] = d.supps
        if d.source not in sources:
            updates["source"] = "+".join(sources + [d.source])
        if not updates:
            return UpsertStats(unchanged=1)
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE draws SET {sets} WHERE draw_date = ?", (*updates.values(), d.key))
        return UpsertStats(updated=1)

    @staticmethod
    def _record_discrepancy(conn, key, field, stored, stored_source, incoming, incoming_source, now):
        conn.execute(
            "INSERT OR IGNORE INTO discrepancies "
            "(draw_date, field, stored, stored_source, incoming, incoming_source, detected_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (key, field, json.dumps(stored), stored_source, json.dumps(incoming), incoming_source, now),
        )

    def replace_draw(self, d: Draw) -> None:
        """Explicit overwrite, used when the user resolves a discrepancy in the UI."""
        supps = list(d.supps) if d.supps else [None, None]
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO draws VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (d.key, d.draw_number, *d.numbers, *supps, d.source, utcnow()),
            )
            conn.execute("UPDATE discrepancies SET resolved = 1 WHERE draw_date = ?", (d.key,))

    def resolve_discrepancy(self, disc_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE discrepancies SET resolved = 1 WHERE id = ?", (disc_id,))

    def discrepancies(self, include_resolved: bool = False) -> list[dict]:
        sql = "SELECT * FROM discrepancies"
        if not include_resolved:
            sql += " WHERE resolved = 0"
        with self.connect() as conn:
            rows = conn.execute(sql + " ORDER BY draw_date DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["stored"] = json.loads(d["stored"])
            d["incoming"] = json.loads(d["incoming"])
            out.append(d)
        return out

    def draw_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]

    def latest_draw_date(self) -> date | None:
        with self.connect() as conn:
            v = conn.execute("SELECT MAX(draw_date) FROM draws").fetchone()[0]
        return date.fromisoformat(v) if v else None

    def get_draw(self, d: date) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM draws WHERE draw_date = ?", (d.isoformat(),)).fetchone()
        return dict(row) if row else None

    def draws_df(self) -> pd.DataFrame:
        """All draws, oldest first, with draw_date as a datetime.date column."""
        with self.connect() as conn:
            df = pd.read_sql_query("SELECT * FROM draws ORDER BY draw_date", conn)
        df["draw_date"] = pd.to_datetime(df["draw_date"]).dt.date
        for col in ("draw_number", "supp1", "supp2"):
            df[col] = df[col].astype("Int64")
        return df

    def search_draws(self, q: str = "", page: int = 1, per_page: int = 25) -> tuple[list[dict], int]:
        """Search by date fragment (e.g. '2024-03') or by numbers ('7 21' = draws containing both)."""
        where, params = [], []
        tokens = q.replace(",", " ").split()
        for tok in tokens:
            if tok.isdigit() and int(tok) <= 45:
                n = int(tok)
                where.append("(? IN (n1,n2,n3,n4,n5,n6,supp1,supp2))")
                params.append(n)
            else:
                where.append("(draw_date LIKE ? OR CAST(draw_number AS TEXT) = ?)")
                params.extend([f"%{tok}%", tok])
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM draws{clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM draws{clause} ORDER BY draw_date DESC LIMIT ? OFFSET ?",
                (*params, per_page, (page - 1) * per_page),
            ).fetchall()
        return [dict(r) for r in rows], total

    # ---------------------------------------------------------------- key/value + log
    def kv_get(self, key: str, default=None):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, key: str, value) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def log(self, message: str, level: str = "INFO") -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO fetch_log (ts, level, message) VALUES (?,?,?)", (utcnow(), level, message))
            conn.execute("DELETE FROM fetch_log WHERE id NOT IN (SELECT id FROM fetch_log ORDER BY id DESC LIMIT 500)")

    def recent_log(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM fetch_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
