"""Plain-text copies of the database kept in the git repo (data/), for the cloud job.

The GitHub Actions run starts with an empty database each week, so the draws,
the stored suggestion sets and the latest backtest live in the repo as CSV/JSON.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .db import Database
from .importer import import_csv_file

DRAWS_CSV = "draws.csv"
SUGGESTIONS_CSV = "suggestions.csv"
BACKTEST_JSON = "backtest.json"
SETTINGS_JSON = "settings.json"

DRAW_COLS = ["draw_date", "draw_number", "n1", "n2", "n3", "n4", "n5", "n6", "supp1", "supp2", "source"]
SUGGESTION_COLS = [
    "target_draw_date", "kind", "seed", "rank", "numbers", "score", "explanation",
    "params_hash", "params_json", "data_through", "algo_version", "created_at",
]


def export_draws(db: Database, path: Path) -> int:
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {', '.join(DRAW_COLS)} FROM draws ORDER BY draw_date").fetchall()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(DRAW_COLS)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
    return len(rows)


def export_suggestions(db: Database, path: Path, kind: str = "weekly") -> int:
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(SUGGESTION_COLS)} FROM suggestions WHERE kind = ? ORDER BY target_draw_date, created_at, rank",
            (kind,),
        ).fetchall()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(SUGGESTION_COLS)
        w.writerows(rows)
    return len(rows)


def import_suggestions(db: Database, path: Path) -> int:
    """Restore stored sets with their original created_at (which decides 'made before the draw')."""
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with db.connect() as conn:
        for r in rows:
            conn.execute(
                f"INSERT OR IGNORE INTO suggestions ({', '.join(SUGGESTION_COLS)}) VALUES ({', '.join('?' * len(SUGGESTION_COLS))})",
                [r[c] for c in SUGGESTION_COLS],
            )
    return len(rows)


def load_repo_state(db: Database, data_dir: Path) -> dict:
    """Fill an empty database from data/. Returns counts for the log."""
    out = {"draws": 0, "suggestions": 0, "backtest": False, "settings": False}
    draws = data_dir / DRAWS_CSV
    if draws.exists():
        rep = import_csv_file(db, draws, source="repo")
        if rep.errors:
            raise ValueError(f"{draws} has invalid rows: {rep.errors[:5]}")
        out["draws"] = rep.rows
        db.kv_set("full_backfill_done", True)  # the repo copy already has supps and draw numbers
    out["suggestions"] = import_suggestions(db, data_dir / SUGGESTIONS_CSV)
    bt = data_dir / BACKTEST_JSON
    if bt.exists():
        db.kv_set("backtest:last", json.loads(bt.read_text()))
        out["backtest"] = True
    st = data_dir / SETTINGS_JSON
    if st.exists():
        db.kv_set("settings", json.loads(st.read_text()))
        out["settings"] = True
    return out


def save_repo_state(db: Database, data_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    out = {"draws": export_draws(db, data_dir / DRAWS_CSV),
           "suggestions": export_suggestions(db, data_dir / SUGGESTIONS_CSV)}
    bt = db.kv_get("backtest:last")
    if bt:
        (data_dir / BACKTEST_JSON).write_text(json.dumps(bt, indent=1, sort_keys=True) + "\n")
    return out
