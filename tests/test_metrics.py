from datetime import date

import numpy as np
import pytest

from helpers import SMALL, draws_df
from lottolens.analysis.core import apply_window, indicator
from lottolens.analysis.metrics import (
    combo_structure,
    expected_pair_count,
    frequency,
    gaps,
    hot_cold,
    pair_matrix,
    randomness_check,
    structure,
    supp_frequency,
)


def test_frequency():
    f = frequency(SMALL)
    assert f[1] == 3
    assert f[2] == f[3] == f[10] == f[20] == f[45] == 2
    assert f[4] == f[30] == f[40] == 1
    assert f[44] == 0
    assert f.sum() == 24


def test_supp_frequency_skips_draws_without_supps():
    f, n = supp_frequency(SMALL)
    assert n == 3
    assert f[2] == 2 and f[1] == f[3] == f[7] == f[8] == 1 and f.sum() == 6


def test_gaps():
    g = gaps(SMALL)
    assert g.loc[1, "current_gap"] == 0 and g.loc[1, "avg_gap"] == pytest.approx(1.5)
    assert g.loc[2, "current_gap"] == 2 and g.loc[2, "avg_gap"] == 1.0
    assert g.loc[6, "current_gap"] == 3 and np.isnan(g.loc[6, "avg_gap"])
    assert g.loc[44, "current_gap"] == 4 and g.loc[44, "appearances"] == 0
    assert g.loc[2, "overdue_ratio"] == 2.0
    assert g.loc[6, "overdue_ratio"] == pytest.approx(3 / 7.5)


def test_hot_cold_z_scores():
    h = hot_cold(SMALL, lookbacks=(2, 10))
    assert h.loc[45, "count_2"] == 2
    assert h.loc[45, "expected_2"] == pytest.approx(2 * 6 / 45)
    assert h.loc[45, "z_2"] == pytest.approx((2 - 0.26667) / 0.48074, rel=1e-4)
    # lookback longer than history is capped at the available draws
    assert h.loc[1, "count_10"] == 3 and h.loc[1, "expected_10"] == pytest.approx(4 * 6 / 45)


def test_pair_matrix():
    m = pair_matrix(SMALL)
    assert m.shape == (45, 45) and (m == m.T).all() and m.trace() == 0
    assert m[0, 1] == 2  # (1, 2)
    assert m[9, 19] == 2  # (10, 20)
    assert m[0, 44] == 1  # (1, 45)
    assert m[1, 44] == 0  # (2, 45)
    assert m.sum() == 4 * 15 * 2  # 15 pairs per draw, counted both ways
    assert expected_pair_count(1980) == pytest.approx(30)


def test_structure():
    s = structure(SMALL)
    d1, d4 = s.iloc[0], s.iloc[3]
    assert (d1["sum"], d1["odd"], d1["low"], d1["consecutive_pairs"], d1["longest_run"], d1["decade_groups"]) == (21, 3, 6, 5, 6, 1)
    assert (d4["sum"], d4["odd"], d4["low"], d4["consecutive_pairs"], d4["longest_run"], d4["decade_groups"]) == (142, 4, 3, 1, 2, 4)
    one = combo_structure(np.array([[45, 9, 10, 20, 30, 40]]))  # unsorted input
    assert one.loc[0, "decade_groups"] == 5 and one.loc[0, "longest_run"] == 2


def test_chi_square_matches_formula():
    r = randomness_check(SMALL)
    obs = frequency(SMALL).to_numpy()
    e = obs.sum() / 45
    assert r.statistic == pytest.approx(((obs - e) ** 2 / e).sum())
    assert r.dof == 44 and 0 <= r.p_value <= 1
    assert "little power" in r.explanation


def test_chi_square_flags_obvious_bias():
    biased = draws_df([(f"2026-01-{d:02d}", [1, 2, 3, 4, 5, 6]) for d in (3, 10, 17, 24, 31)] * 1)
    assert randomness_check(biased).p_value < 0.01


def test_apply_window():
    df = draws_df([("2023-10-07", [1, 2, 3, 4, 5, 6]), ("2024-10-12", [1, 2, 3, 4, 5, 7]), ("2026-10-10", [1, 2, 3, 4, 5, 8])])
    assert len(apply_window(df, "1")) == 1
    assert len(apply_window(df, "2")) == 2
    assert len(apply_window(df, "all")) == 3
    assert len(apply_window(df, 5, as_of=date(2024, 12, 31))) == 2  # walk-forward cut-off


def test_indicator_ignores_missing():
    x = indicator(SMALL, ["supp1", "supp2"])
    assert x[1].sum() == 0 and x.sum() == 6
