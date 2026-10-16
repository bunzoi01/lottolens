"""Saturday Lotto prize divisions and their exact odds for one game.

Div 1: 6 winning numbers
Div 2: 5 winning numbers + 1 supplementary
Div 3: 5 winning numbers
Div 4: 4 winning numbers
Div 5: 3 winning numbers + 1 supplementary
Div 6: 1 or 2 winning numbers + both supplementaries
"""

from __future__ import annotations

from math import comb

import numpy as np

DIVISIONS = [1, 2, 3, 4, 5, 6]
DIVISION_LABELS = {
    1: "Div 1 (6)",
    2: "Div 2 (5 + supp)",
    3: "Div 3 (5)",
    4: "Div 4 (4)",
    5: "Div 5 (3 + supp)",
    6: "Div 6 (1-2 + both supps)",
}


def division(matches: int, supp_matches: int | None) -> int | None:
    """Prize division for one game, or None for no prize.

    supp_matches=None means the draw's supps are unknown: 5 matches then scores
    as Div 3 (Div 2 can't be confirmed) and Divs 5-6 can't be awarded.
    """
    if matches == 6:
        return 1
    if matches == 5:
        return 2 if supp_matches else 3
    if matches == 4:
        return 4
    if supp_matches is None:
        return None
    if matches == 3 and supp_matches >= 1:
        return 5
    if matches in (1, 2) and supp_matches == 2:
        return 6
    return None


def divisions_vec(matches: np.ndarray, supp_matches: np.ndarray) -> np.ndarray:
    """Vectorised division(); 0 = no prize."""
    m, s = np.asarray(matches), np.asarray(supp_matches)
    out = np.zeros(m.shape, dtype=np.int8)
    out[(m == 3) & (s >= 1)] = 5
    out[((m == 1) | (m == 2)) & (s == 2)] = 6
    out[m == 4] = 4
    out[(m == 5) & (s == 0)] = 3
    out[(m == 5) & (s >= 1)] = 2
    out[m == 6] = 1
    return out


def division_probabilities() -> dict[int, float]:
    """Exact chance of each division for one random game (6 winners, 2 supps, 37 others)."""
    total = comb(45, 6)

    def p(m: int, s: int) -> float:
        rest = 6 - m - s
        if rest < 0:
            return 0.0
        return comb(6, m) * comb(2, s) * comb(37, rest) / total

    return {
        1: p(6, 0),
        2: p(5, 1),
        3: p(5, 0),
        4: sum(p(4, s) for s in range(3)),
        5: p(3, 1) + p(3, 2),
        6: p(1, 2) + p(2, 2),
    }


def any_prize_probability() -> float:
    return sum(division_probabilities().values())
