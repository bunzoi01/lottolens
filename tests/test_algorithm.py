from datetime import date
from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from lottolens.algorithm.suggest import (
    combo_structure,
    sample_candidates,
    select_diverse,
    suggest,
    weekly_seed,
)
from lottolens.config import Settings


def synthetic_history(n=300, seed=1):
    rng = np.random.default_rng(seed)
    start = date(2020, 1, 4)
    rows = []
    for i in range(n):
        nums = np.sort(rng.choice(np.arange(1, 46), 6, replace=False))
        rows.append({"draw_date": start + pd.Timedelta(weeks=i).to_pytimedelta(), **{f"n{j+1}": int(v) for j, v in enumerate(nums)}})
    df = pd.DataFrame(rows)
    df["supp1"] = pd.array([None] * n, dtype="Int64")
    df["supp2"] = pd.array([None] * n, dtype="Int64")
    return df


HIST = synthetic_history()
TARGET = HIST["draw_date"].iloc[-1] + pd.Timedelta(weeks=1).to_pytimedelta()
FAST = Settings(n_candidates=20_000)


def test_sampling_is_without_replacement_and_follows_weights():
    rng = np.random.default_rng(0)
    p = np.ones(45)
    p[0] = 20  # number 1 heavily weighted
    c = sample_candidates(p / p.sum(), 5000, rng)
    assert c.shape[1] == 6
    assert all(len(set(r)) == 6 for r in c)
    assert (c == 1).any(axis=1).mean() > 0.5


def test_diversity_constraints_hold():
    s = suggest(HIST, TARGET, FAST, seed=42)
    combos = [set(c.numbers) for c in s.combos]
    assert len(combos) == 10
    assert all(len(a & b) <= 2 for a, b in combinations(combos, 2))
    counts = pd.Series([n for c in combos for n in c]).value_counts()
    assert counts.max() <= 3


def test_select_diverse_on_tiny_input():
    combos = np.array([[1, 2, 3, 4, 5, 6], [1, 2, 3, 7, 8, 9], [1, 2, 10, 11, 12, 13], [1, 14, 15, 16, 17, 18], [1, 19, 20, 21, 22, 23]])
    scores = np.array([5, 4, 3, 2, 1])
    picks = select_diverse(combos, scores, k=5, max_overlap=2, max_uses=3)
    # #1 shares 3 with #0 -> rejected; 1 appears in #0, #2, #3 -> #4 rejected by max_uses
    assert picks == [0, 2, 3]


def test_structure_filters_hold():
    st = Settings(n_candidates=20_000)
    s = suggest(HIST, TARGET, st, seed=7)
    arr = np.array([c.numbers for c in s.combos])
    info = combo_structure(arr)
    sums = HIST[[f"n{i}" for i in range(1, 7)]].sum(axis=1)
    lo, hi = np.quantile(sums, [0.15, 0.85])
    assert info["sum"].between(lo, hi).all()
    assert info["odd"].between(2, 4).all() and info["low"].between(2, 4).all()
    assert (info["longest_run"] <= 2).all() and (info["decade_groups"] >= 3).all()


def test_seeded_determinism():
    a = suggest(HIST, TARGET, FAST, seed=weekly_seed(TARGET))
    b = suggest(HIST, TARGET, FAST, seed=weekly_seed(TARGET))
    assert [c.numbers for c in a.combos] == [c.numbers for c in b.combos]
    c = suggest(HIST, TARGET, FAST, seed=weekly_seed(TARGET) + 1)
    assert [x.numbers for x in a.combos] != [x.numbers for x in c.combos]


def test_weekly_seed_changes_with_draw_date():
    assert weekly_seed(date(2026, 10, 17)) == weekly_seed(date(2026, 10, 17))
    assert weekly_seed(date(2026, 10, 17)) != weekly_seed(date(2026, 10, 24))


def test_suggest_ignores_future_data():
    cut = HIST["draw_date"].iloc[200]
    a = suggest(HIST, cut, FAST, seed=1)
    b = suggest(HIST.iloc[:200], cut, FAST, seed=1)
    assert [c.numbers for c in a.combos] == [c.numbers for c in b.combos]
    assert a.data_through == HIST["draw_date"].iloc[199]


def test_explanations_present():
    s = suggest(HIST, TARGET, FAST, seed=3)
    for c in s.combos:
        assert "sum" in c.explanation and "odd" in c.explanation and "hot" in c.explanation


def test_weekly_set_is_stable_and_stored(db):
    from lottolens.algorithm.store import current_set, regenerate, weekly_set
    from lottolens.data.validate import make_draw

    db.upsert_draws(
        make_draw(r.draw_date, [getattr(r, f"n{i}") for i in range(1, 7)], source="t")
        for r in HIST.itertuples()
        if r.draw_date.weekday() == 5
    )
    w1 = weekly_set(db, FAST)
    w2 = weekly_set(db, FAST)
    assert [c.numbers for c in w1.combos] == [c.numbers for c in w2.combos]
    assert len(w1.combos) == 10 and w1.kind == "weekly"
    r = regenerate(db, FAST)
    assert r.kind == "regenerate" and current_set(db, FAST).seed == r.seed
