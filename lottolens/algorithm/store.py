"""Persist suggestion sets and fetch this week's set."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import date

from ..config import Settings
from ..data.dates import next_draw_after
from ..data.db import Database, utcnow
from .suggest import ALGO_VERSION, SuggestionSet, suggest, weekly_seed


@dataclass
class StoredCombo:
    id: int
    rank: int
    numbers: tuple[int, ...]
    score: float
    explanation: str


@dataclass
class StoredSet:
    target_draw_date: date
    kind: str
    seed: int
    params_hash: str
    data_through: str
    created_at: str
    algo_version: str
    combos: list[StoredCombo]


def target_draw(db: Database) -> date | None:
    """The draw the current suggestions are for: the one after the latest stored draw."""
    latest = db.latest_draw_date()
    return next_draw_after(latest) if latest else None


def save_set(db: Database, s: SuggestionSet, kind: str) -> None:
    now = utcnow()
    with db.connect() as conn:
        for rank, c in enumerate(s.combos, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO suggestions (target_draw_date, kind, seed, rank, numbers, score, "
                "explanation, params_hash, params_json, data_through, algo_version, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    s.target_draw_date.isoformat(), kind, s.seed, rank, ",".join(map(str, c.numbers)),
                    c.score, c.explanation, s.params_hash, json.dumps(s.params, sort_keys=True),
                    s.data_through.isoformat() if s.data_through else "", s.algo_version, now,
                ),
            )


def load_set(db: Database, target: date, kind: str | None = None, params_hash: str | None = None,
             seed: int | None = None) -> StoredSet | None:
    """Most recently created set for a target date matching the filters."""
    where, params = ["target_draw_date = ?"], [target.isoformat()]
    for col, val in (("kind", kind), ("params_hash", params_hash), ("seed", seed)):
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    with db.connect() as conn:
        head = conn.execute(
            f"SELECT kind, seed, params_hash, created_at FROM suggestions WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            params,
        ).fetchone()
        if head is None:
            return None
        rows = conn.execute(
            "SELECT * FROM suggestions WHERE target_draw_date = ? AND kind = ? AND seed = ? AND params_hash = ? "
            "ORDER BY rank",
            (target.isoformat(), head["kind"], head["seed"], head["params_hash"]),
        ).fetchall()
    combos = [
        StoredCombo(r["id"], r["rank"], tuple(int(x) for x in r["numbers"].split(",")), r["score"], r["explanation"])
        for r in rows
    ]
    first = rows[0]
    return StoredSet(target, first["kind"], first["seed"], first["params_hash"], first["data_through"],
                     first["created_at"], first["algo_version"], combos)


def weekly_set(db: Database, settings: Settings) -> StoredSet | None:
    """This week's deterministic set, generating and storing it on first request."""
    target = target_draw(db)
    if target is None:
        return None
    existing = load_set(db, target, "weekly", settings.params_hash())
    if existing and existing.algo_version == ALGO_VERSION:
        return existing
    s = suggest(db.draws_df(), target, settings, weekly_seed(target))
    save_set(db, s, "weekly")
    return load_set(db, target, "weekly", settings.params_hash())


def regenerate(db: Database, settings: Settings) -> StoredSet | None:
    """A fresh set with a random seed (stored so it can be checked later too)."""
    target = target_draw(db)
    if target is None:
        return None
    seed = secrets.randbits(60)
    save_set(db, suggest(db.draws_df(), target, settings, seed), "regenerate")
    return load_set(db, target, "regenerate", seed=seed)


def current_set(db: Database, settings: Settings) -> StoredSet | None:
    """What the This Week page shows: the latest regenerated set if any, else the weekly set."""
    target = target_draw(db)
    if target is None:
        return None
    regen = load_set(db, target, "regenerate", settings.params_hash())
    weekly = weekly_set(db, settings)
    if regen and weekly and regen.combos[0].id > weekly.combos[0].id:
        return regen
    return weekly
