from datetime import datetime

from conftest import FIXTURES
from lottolens.data.dates import SYDNEY
from lottolens.fetch.lottonumbers import parse_results_html
from lottolens.scheduler.gate import should_run_scheduled
from lottolens.scheduler.notify import _applescript_string


def seed(db, upto_last=True):
    draws = parse_results_html((FIXTURES / "lottonumbers_2026_archive.html").read_text())
    db.upsert_draws(draws if upto_last else draws[:-1])


def test_gate_up_to_date(db):
    seed(db)
    ok, why = should_run_scheduled(db, datetime(2026, 10, 11, 10, 30, tzinfo=SYDNEY))
    assert not ok and "up to date" in why


def test_gate_sunday_window_once_then_monday_retry(db):
    seed(db, upto_last=False)  # 10 Oct missing
    assert not should_run_scheduled(db, datetime(2026, 10, 11, 9, 30, tzinfo=SYDNEY))[0]  # before 10:00
    assert should_run_scheduled(db, datetime(2026, 10, 11, 10, 5, tzinfo=SYDNEY))[0]
    assert not should_run_scheduled(db, datetime(2026, 10, 11, 11, 5, tzinfo=SYDNEY))[0]  # once per window
    assert should_run_scheduled(db, datetime(2026, 10, 12, 10, 5, tzinfo=SYDNEY))[0]  # Monday retry
    assert not should_run_scheduled(db, datetime(2026, 10, 13, 10, 5, tzinfo=SYDNEY))[0]  # Tuesday: no


def test_gate_uses_sydney_time_not_mac_time(db):
    from zoneinfo import ZoneInfo

    seed(db, upto_last=False)
    # 23:05 UTC Saturday 10 Oct = 10:05 Sunday 11 Oct in Sydney (AEDT)
    assert should_run_scheduled(db, datetime(2026, 10, 10, 23, 5, tzinfo=ZoneInfo("UTC")))[0]


def test_applescript_quoting():
    assert _applescript_string('say "hi" \\ ok') == '"say \\"hi\\" \\\\ ok"'
