"""Live tracking: score stored suggestions once their draw result is known."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from ..data.dates import SYDNEY
from ..data.db import Database, utcnow
from .prizes import division

# A set only counts as a genuine "live" pick if it was stored before the draw.
DRAW_TIME_HOUR = 19


def score_pending(db: Database) -> int:
    """Score every stored suggestion whose draw has a result and hasn't been scored. Returns count."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.id, s.numbers, d.draw_date, d.n1, d.n2, d.n3, d.n4, d.n5, d.n6, d.supp1, d.supp2 "
            "FROM suggestions s JOIN draws d ON d.draw_date = s.target_draw_date "
            "LEFT JOIN suggestion_results r ON r.suggestion_id = s.id WHERE r.suggestion_id IS NULL"
        ).fetchall()
        now = utcnow()
        for r in rows:
            nums = {int(x) for x in r["numbers"].split(",")}
            winners = {r[f"n{i}"] for i in range(1, 7)}
            supps = {r["supp1"], r["supp2"]} if r["supp1"] is not None else None
            m = len(nums & winners)
            s = len(nums & supps) if supps else None
            conn.execute(
                "INSERT INTO suggestion_results VALUES (?,?,?,?,?,?)",
                (r["id"], r["draw_date"], m, s, division(m, s), now),
            )
    return len(rows)


def _made_before_draw(created_at: str, draw_date: str) -> bool:
    created = datetime.fromisoformat(created_at)
    d = date.fromisoformat(draw_date)
    cutoff = datetime(d.year, d.month, d.day, DRAW_TIME_HOUR, tzinfo=SYDNEY)
    return created < cutoff


def live_history(db: Database, limit: int = 52) -> list[dict]:
    """Per draw: the weekly set that existed before the draw, and how it did."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.target_draw_date, s.params_hash, s.seed, s.created_at, s.numbers, s.rank, "
            "r.matches, r.supp_matches, r.division "
            "FROM suggestions s JOIN suggestion_results r ON r.suggestion_id = s.id "
            "WHERE s.kind = 'weekly' ORDER BY s.target_draw_date DESC, s.created_at DESC, s.rank"
        ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        if not _made_before_draw(r["created_at"], r["target_draw_date"]):
            continue
        key = r["target_draw_date"]
        entry = out.setdefault(key, {"draw_date": key, "set": (r["params_hash"], r["seed"], r["created_at"]), "games": []})
        if entry["set"] != (r["params_hash"], r["seed"], r["created_at"]):
            continue  # an older set for the same draw; keep only the latest pre-draw set
        entry["games"].append(
            {"numbers": [int(x) for x in r["numbers"].split(",")], "matches": r["matches"],
             "supp_matches": r["supp_matches"], "division": r["division"]}
        )
    history = []
    for key in sorted(out, reverse=True)[:limit]:
        e = out[key]
        divs = [g["division"] for g in e["games"] if g["division"]]
        history.append(
            {
                "draw_date": key,
                "games": e["games"],
                "prize_games": len(divs),
                "best_division": min(divs) if divs else None,
                "best_matches": max(g["matches"] for g in e["games"]),
                "mean_matches": float(np.mean([g["matches"] for g in e["games"]])),
            }
        )
    return history


def live_totals(history: list[dict]) -> dict:
    games = sum(len(h["games"]) for h in history)
    prizes = sum(h["prize_games"] for h in history)
    return {"draws": len(history), "games": games, "prize_games": prizes}
