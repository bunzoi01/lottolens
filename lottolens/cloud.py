"""The weekly cloud run (GitHub Actions): repo data -> refresh -> backtest -> repo data + static site.

Starts from an empty, throwaway database each time; everything that must
survive between runs is written back to data/ and committed by the workflow.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .algorithm.suggest import ALGO_VERSION
from .backtest.walkforward import run_backtest
from .config import load_settings
from .data.db import Database
from .data.importer import ensure_seeded
from .data.repo_state import load_repo_state, save_repo_state
from .pipeline import run_refresh
from .site import build_site

log = logging.getLogger("lottolens.cloud")


@dataclass
class CloudReport:
    loaded: dict = field(default_factory=dict)
    refresh: str = ""
    errors: list[str] = field(default_factory=list)
    backtest: str = "reused"
    latest_draw: str = ""
    target: str = ""
    files: int = 0

    def markdown(self) -> str:
        lines = [
            "### LottoLens weekly update",
            f"- Latest stored draw: **{self.latest_draw}**",
            f"- Suggestions built for: **{self.target}**",
            f"- Refresh: {self.refresh}",
            f"- Backtest: {self.backtest}",
            f"- Site files: {self.files}",
        ]
        if self.errors:
            lines.append(f"- :warning: Errors: {'; '.join(self.errors)}")
        return "\n".join(lines) + "\n"


def _backtest_is_current(db: Database, new_draws: bool) -> bool:
    bt = db.kv_get("backtest:last")
    if not bt or new_draws:
        return False
    settings = load_settings(db)
    return bt.get("params_hash") == settings.params_hash() and bt.get("algo_version") == ALGO_VERSION \
        and bt.get("last_draw") == str(db.latest_draw_date())


def run_cloud(data_dir: Path, site_dir: Path, fetch: bool = True) -> CloudReport:
    rep = CloudReport()
    with tempfile.TemporaryDirectory(prefix="lottolens-") as tmp:
        db = Database(Path(tmp) / "lotto.db")
        rep.loaded = load_repo_state(db, data_dir)
        if not rep.loaded["draws"]:
            ensure_seeded(db, paths.SEED_CSV)  # very first run: original CSV, then the full archive back-fill

        pr = run_refresh(db, fetch=fetch)
        rep.refresh = pr.summary()
        rep.errors = list(pr.errors)

        if not _backtest_is_current(db, bool(pr.new_draws)):
            res = run_backtest(db.draws_df(), load_settings(db))
            db.kv_set("backtest:last", res.to_dict())
            rep.backtest = f"re-run: {res.algo['prize_games']} prize games vs random {res.random['prize_games']:.1f}"

        save_repo_state(db, data_dir)
        rep.files = len(build_site(db, site_dir))
        rep.latest_draw = str(db.latest_draw_date())
        rep.target = str(pr.target)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(rep.markdown())
    for e in rep.errors:
        print(f"::warning title=LottoLens refresh::{e}")
    return rep
