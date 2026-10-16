import pytest
from fastapi.testclient import TestClient

from conftest import FIXTURES
from lottolens.config import Settings, save_settings
from lottolens.fetch.lottonumbers import parse_results_html


@pytest.fixture
def client(db):
    for f in ("lottonumbers_1986_archive.html", "lottonumbers_2026_archive.html"):
        db.upsert_draws(parse_results_html((FIXTURES / f).read_text()))
    db.kv_set("full_backfill_done", True)
    save_settings(db, Settings(lottonumbers_enabled=False))
    from lottolens.web.app import create_app

    with TestClient(create_app(db, background=False)) as c:
        yield c


def test_this_week(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Sat 17 Oct 2026" in r.text
    assert "gamblinghelponline.org.au" in r.text and "1800 858 858" in r.text
    assert r.text.count('class="combo"') == 10


def test_regenerate_and_export(client):
    r = client.post("/regenerate")
    assert r.status_code == 200 and "Regenerated set" in r.text
    csv = client.get("/export.csv")
    assert csv.status_code == 200 and csv.text.count("\n") == 11


@pytest.mark.parametrize("path", ["/analysis", "/analysis?window=all", "/history", "/history?q=43", "/backtest", "/settings"])
def test_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:500]


def test_manual_entry_validation_and_conflict(client):
    bad = client.post("/history/manual", data={"draw_date": "2026-10-11", "numbers": "1 2 3 4 5 6"})
    assert "not a Saturday" in bad.text
    conflict = client.post("/history/manual", data={"draw_date": "2026-10-10", "numbers": "1 2 3 4 5 6"})
    assert "flagged for review" in conflict.text
    assert "Sources disagree" in client.get("/history").text


def test_csv_upload(client):
    body = "draw_date,n1,n2,n3,n4,n5,n6\n2026-10-10,2,15,16,33,41,43\n"
    r = client.post("/history/import", files={"file": ("x.csv", body, "text/csv")})
    assert "0 new" in r.text and "0 conflicts" in r.text  # same numbers; only the source tag is added


def test_settings_save(client):
    r = client.post("/settings", data={"window": "5", "w_frequency": "50", "w_hot": "0", "w_overdue": "0",
                                       "w_pair": "0", "w_random": "50"}, follow_redirects=True)
    assert r.status_code == 200 and "Saved" in r.text
    assert 'value="5" selected' in r.text
