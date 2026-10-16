from datetime import date, datetime

import httpx
import pytest

from conftest import FIXTURES
from lottolens.data.dates import SYDNEY
from lottolens.data.importer import import_csv_text
from lottolens.fetch.http import FetchDisallowed, PoliteClient
from lottolens.fetch.lottonumbers import LottoNumbersProvider, ParseError, parse_results_html
from lottolens.fetch.service import refresh


def test_parse_2026_archive():
    draws = parse_results_html((FIXTURES / "lottonumbers_2026_archive.html").read_text())
    assert len(draws) == 41
    assert draws[0].draw_date == date(2026, 1, 3)
    last = draws[-1]
    assert last.draw_date == date(2026, 10, 10)
    assert last.numbers == (2, 15, 16, 33, 41, 43)
    assert last.supps == (5, 28)
    assert last.draw_number == 4719


def test_parse_1986_archive_matches_seed_start():
    draws = parse_results_html((FIXTURES / "lottonumbers_1986_archive.html").read_text())
    assert len(draws) == 18
    assert draws[0].draw_date == date(1986, 8, 30)
    assert draws[0].numbers == (6, 7, 9, 14, 20, 30)
    assert draws[0].draw_number == 533


def test_parse_latest_page_layout():
    draws = parse_results_html((FIXTURES / "lottonumbers_results.html").read_text())
    assert draws[-1].draw_date == date(2026, 10, 10)
    assert draws[-1].supps == (5, 28)
    assert all(len(d.numbers) == 6 for d in draws)


def test_parse_unknown_layout_raises():
    with pytest.raises(ParseError):
        parse_results_html('<div class="balls-fx"><ul class="balls"><li class="ball">1</li></ul></div>')


# ------------------------------------------------------------ polite client with a mock transport
def make_client(tmp_path, routes, calls):
    def handler(request: httpx.Request):
        calls.append(str(request.url))
        assert "LottoLens" in request.headers["user-agent"]
        body = routes.get(str(request.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)

    return PoliteClient(cache_dir=tmp_path / "cache", min_interval=0, transport=httpx.MockTransport(handler))


def test_robots_disallow_stops(tmp_path):
    calls = []
    routes = {"https://au.lottonumbers.com/robots.txt": "User-Agent: *\nDisallow: /saturday-lotto/"}
    client = make_client(tmp_path, routes, calls)
    with pytest.raises(FetchDisallowed):
        client.get_text("https://au.lottonumbers.com/saturday-lotto/results")
    assert calls == ["https://au.lottonumbers.com/robots.txt"]


def test_cache_prevents_refetch(tmp_path):
    calls = []
    url = "https://au.lottonumbers.com/saturday-lotto/results/2020-archive"
    routes = {"https://au.lottonumbers.com/robots.txt": "User-Agent: *\nDisallow: /en/play/", url: "<html>x</html>"}
    client = make_client(tmp_path, routes, calls)
    assert client.get_text(url, ttl=None) == "<html>x</html>"
    assert client.get_text(url, ttl=None) == "<html>x</html>"
    assert calls.count(url) == 1


def test_rate_limit(tmp_path):
    import time

    calls = []
    routes = {"https://x.test/robots.txt": "", "https://x.test/a": "a", "https://x.test/b": "b"}
    client = make_client(tmp_path, routes, calls)
    client.min_interval = 0.3
    t0 = time.monotonic()
    client.get_text("https://x.test/a")
    client.get_text("https://x.test/b")
    assert time.monotonic() - t0 >= 0.6  # robots + a + b, spaced 0.3s


# ------------------------------------------------------------ back-fill service with a fake provider
class FakeProvider:
    name = "fake"

    def __init__(self):
        self.years = []
        self.all = parse_results_html((FIXTURES / "lottonumbers_2026_archive.html").read_text(), "fake")

    def fetch_year(self, year):
        self.years.append(year)
        return [d for d in self.all if d.draw_date.year == year]

    def fetch_latest(self):
        return self.all[-3:]


def test_backfill_only_missing_draws(db):
    import_csv_text(db, "draw_date,n1,n2,n3,n4,n5,n6\n2025-12-27,3,5,20,26,28,40\n", "seed")
    prov = FakeProvider()
    now = datetime(2026, 10, 16, 12, tzinfo=SYDNEY)
    rep = refresh(db, prov, now=now)
    assert prov.years == [2026]
    assert rep.stats.inserted == 41 and len(rep.new_dates) == 41
    assert db.latest_draw_date() == date(2026, 10, 10)
    rep2 = refresh(db, prov, now=now)
    assert rep2.up_to_date and prov.years == [2026]


def test_backfill_flags_disagreement(db):
    # Stored 3 Oct draw differs from the source -> discrepancy, stored row kept.
    import_csv_text(db, "draw_date,n1,n2,n3,n4,n5,n6\n2026-10-03,1,2,3,4,5,6\n", "manual")
    refresh(db, FakeProvider(), full=True, now=datetime(2026, 10, 16, 12, tzinfo=SYDNEY))
    disc = db.discrepancies()
    assert [(d["draw_date"], d["field"]) for d in disc] == [("2026-10-03", "numbers")]
    assert db.get_draw(date(2026, 10, 3))["n1"] == 1
