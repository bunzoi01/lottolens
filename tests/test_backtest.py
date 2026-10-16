from datetime import date
from math import comb

import numpy as np
import pytest

from lottolens.backtest.prizes import any_prize_probability, division, division_probabilities, divisions_vec
from lottolens.backtest.walkforward import run_backtest, score_games
from lottolens.config import Settings
from test_algorithm import synthetic_history


@pytest.mark.parametrize(
    "m,s,expected",
    [
        (6, 0, 1), (5, 1, 2), (5, 0, 3), (4, 0, 4), (4, 2, 4), (3, 1, 5), (3, 2, 5),
        (3, 0, None), (2, 2, 6), (1, 2, 6), (2, 1, None), (0, 2, None), (0, 0, None),
        (5, None, 3), (3, None, None), (2, None, None),
    ],
)
def test_division_rules(m, s, expected):
    assert division(m, s) == expected
    if s is not None:
        assert divisions_vec(np.array([m]), np.array([s]))[0] == (expected or 0)


def test_score_games():
    winners = np.array([2, 15, 16, 33, 41, 43])
    supps = np.array([5, 28])
    games = np.array(
        [
            [2, 15, 16, 33, 41, 43],  # div 1
            [2, 15, 16, 33, 41, 5],  # 5 + supp -> div 2
            [2, 15, 16, 33, 1, 3],  # 4 -> div 4
            [2, 15, 16, 5, 1, 3],  # 3 + supp -> div 5
            [2, 5, 28, 1, 3, 4],  # 1 + both supps -> div 6
            [1, 3, 4, 6, 7, 8],  # nothing
        ]
    )
    m, s, d = score_games(games, winners, supps)
    assert m.tolist() == [6, 5, 4, 3, 1, 0]
    assert s.tolist() == [0, 1, 0, 1, 2, 0]
    assert d.tolist() == [1, 2, 4, 5, 6, 0]
    _, _, d2 = score_games(games, winners, None)
    assert d2.tolist() == [1, 3, 4, 0, 0, 0]


def test_exact_odds_match_published_odds():
    p = division_probabilities()
    assert 1 / p[1] == pytest.approx(comb(45, 6))  # 1 in 8,145,060
    assert 1 / p[6] == pytest.approx(143.9, abs=0.1)  # published: about 1 in 144
    assert 1 / any_prize_probability() == pytest.approx(85.0, abs=1.0)


def test_walk_forward_backtest_runs_and_is_honest():
    hist = synthetic_history(n=200)
    rng = np.random.default_rng(5)
    supps = []
    for r in hist.itertuples():
        pool = np.setdiff1d(np.arange(1, 46), [r.n1, r.n2, r.n3, r.n4, r.n5, r.n6])
        supps.append(rng.choice(pool, 2, replace=False))
    hist["supp1"] = [int(s[0]) for s in supps]
    hist["supp2"] = [int(s[1]) for s in supps]
    res = run_backtest(hist, Settings(n_candidates=5_000), n_draws=20, random_trials=50)
    assert res.draws == 20 and len(res.per_draw) == 20
    assert res.algo["games"] == 200
    assert 0 <= res.empirical_p <= 1
    assert res.per_draw[-1]["algo_cum"] == res.algo["prize_games"]
    assert res.theory["mean_matches"] == pytest.approx(0.8)
    assert "random" in res.verdict.lower()
