from datetime import date

import pytest

from lottolens.data.importer import import_csv_text, parse_csv
from lottolens.data.validate import DrawValidationError, make_draw
from lottolens.paths import SEED_CSV

GOOD = """draw_date,n1,n2,n3,n4,n5,n6
2026-10-03,9,18,20,32,39,45
2026-10-10,43,15,16,33,41,2
"""


def test_parse_sorts_and_validates():
    draws, errors = parse_csv(GOOD, "test")
    assert errors == []
    assert draws[1].numbers == (2, 15, 16, 33, 41, 43)


@pytest.mark.parametrize(
    "row,msg",
    [
        ("2026-10-10,1,2,3,4,5,5", "not unique"),
        ("2026-10-10,1,2,3,4,5,46", "within 1-45"),
        ("2026-10-11,1,2,3,4,5,6", "not a Saturday"),
        ("2099-01-03,1,2,3,4,5,6", "future"),
        ("not-a-date,1,2,3,4,5,6", "invalid date"),
    ],
)
def test_parse_rejects_bad_rows(row, msg):
    draws, errors = parse_csv("draw_date,n1,n2,n3,n4,n5,n6\n" + row, "test")
    assert draws == []
    assert msg in errors[0]


def test_missing_columns():
    _, errors = parse_csv("date,a,b\n", "test")
    assert "missing required column" in errors[0]


def test_supps_must_differ_from_winners():
    with pytest.raises(DrawValidationError, match="differ"):
        make_draw("2026-10-10", [2, 15, 16, 33, 41, 43], [2, 28])


def test_import_is_idempotent_and_enriches(db):
    r1 = import_csv_text(db, GOOD, "seed")
    assert r1.stats.inserted == 2
    r2 = import_csv_text(db, GOOD, "seed")
    assert r2.stats.unchanged == 2 and db.draw_count() == 2
    enriched = "draw_date,n1,n2,n3,n4,n5,n6,supp1,supp2,draw_number\n2026-10-10,2,15,16,33,41,43,5,28,4719\n"
    r3 = import_csv_text(db, enriched, "web")
    assert r3.stats.updated == 1
    row = db.get_draw(date(2026, 10, 10))
    assert (row["supp1"], row["supp2"], row["draw_number"], row["source"]) == (5, 28, 4719, "seed+web")


def test_conflict_is_flagged_not_overwritten(db):
    import_csv_text(db, GOOD, "seed")
    r = import_csv_text(db, "draw_date,n1,n2,n3,n4,n5,n6\n2026-10-10,1,15,16,33,41,43\n", "other")
    assert r.stats.conflicts == 1
    assert db.get_draw(date(2026, 10, 10))["n1"] == 2
    disc = db.discrepancies()
    assert len(disc) == 1 and disc[0]["field"] == "numbers" and disc[0]["incoming_source"] == "other"


def test_seed_csv_is_valid():
    draws, errors = parse_csv(SEED_CSV.read_text(), "seed")
    assert errors == []
    assert len(draws) == 2053
    assert draws[0].draw_date == date(1986, 8, 30) and draws[-1].draw_date == date(2025, 12, 27)
