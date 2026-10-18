import json
import re

import pytest

from conftest import FIXTURES
from lottolens.config import Settings, save_settings
from lottolens.data.repo_state import load_repo_state, save_repo_state
from lottolens.fetch.lottonumbers import parse_results_html


@pytest.fixture
def seeded(db):
    for f in ("lottonumbers_1986_archive.html", "lottonumbers_2026_archive.html"):
        db.upsert_draws(parse_results_html((FIXTURES / f).read_text()))
    save_settings(db, Settings(lottonumbers_enabled=False))
    return db


def test_static_site_builds_relative_pwa(seeded, tmp_path):
    from lottolens.site import build_site

    out = tmp_path / "site"
    files = build_site(seeded, out)
    for f in ("index.html", "analysis.html", "analysis-all.html", "history.html", "backtest.html",
              "picks.csv", "draws.csv", "manifest.webmanifest", "sw.js", "robots.txt", ".nojekyll"):
        assert (out / f).exists(), f
    index = (out / "index.html").read_text()
    assert index.count('class="combo"') == 10
    assert "gamblinghelponline.org.au" in index and "1800 858 858" in index
    assert 'rel="manifest"' in index and "apple-touch-icon" in index and 'name="robots" content="noindex' in index
    assert "Regenerate" not in index and "/settings" not in index
    # No root-relative links: the site lives under /<repo>/ on GitHub Pages.
    for page in ("index.html", "analysis.html", "history.html", "backtest.html"):
        html = (out / page).read_text()
        assert not re.search(r'(?:href|src)="/(?!/)', html), page
    manifest = json.loads((out / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone" and manifest["scope"] == "./"
    for icon in manifest["icons"]:
        assert (out / icon["src"]).exists()
    # Everything the service worker precaches must exist.
    precache = json.loads(re.search(r"const PRECACHE = (\[.*?\]);", (out / "sw.js").read_text(), re.S).group(1))
    for rel in precache:
        assert rel == "./" or (out / rel).exists(), rel
    assert len((out / "picks.csv").read_text().splitlines()) == 11
    assert set(files) >= {"index.html", "sw.js"}


def test_repo_state_round_trip_keeps_created_at(seeded, tmp_path):
    from lottolens.algorithm.store import load_set, target_draw, weekly_set
    from lottolens.data.db import Database

    s = weekly_set(seeded, Settings(lottonumbers_enabled=False))
    data = tmp_path / "data"
    counts = save_repo_state(seeded, data)
    assert counts["draws"] == seeded.draw_count() and counts["suggestions"] == 10

    fresh = Database(tmp_path / "fresh.db")
    loaded = load_repo_state(fresh, data)
    assert loaded["draws"] == seeded.draw_count()
    assert fresh.get_draw(seeded.latest_draw_date())["supp1"] is not None
    restored = load_set(fresh, target_draw(fresh), "weekly")
    assert [c.numbers for c in restored.combos] == [c.numbers for c in s.combos]
    assert restored.created_at == s.created_at
    assert fresh.kv_get("full_backfill_done") is True


def test_cloud_run_offline(seeded, tmp_path):
    from lottolens.cloud import run_cloud

    data = tmp_path / "data"
    save_repo_state(seeded, data)
    (data / "settings.json").write_text(json.dumps(Settings(lottonumbers_enabled=False).to_dict()))
    rep = run_cloud(data, tmp_path / "site", fetch=False)
    assert rep.latest_draw == "2026-10-10" and rep.target == "2026-10-17"
    assert rep.backtest.startswith("re-run")
    assert (data / "backtest.json").exists() and (data / "suggestions.csv").exists()
    assert (tmp_path / "site" / "index.html").exists()
    # Second run with nothing new reuses the stored backtest.
    rep2 = run_cloud(data, tmp_path / "site", fetch=False)
    assert rep2.backtest == "reused"
