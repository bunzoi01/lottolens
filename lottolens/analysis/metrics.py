"""Frequency, hot/cold, gaps, pairs, structure and randomness metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .core import N, NUMBERS, P_IN_DRAW, PICK, SUPP_COLS, indicator, numbers_array

LOW_MAX = 22  # low = 1-22, high = 23-45
DECADES = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 45)]
DECADE_LABELS = ["1-9", "10-19", "20-29", "30-39", "40-45"]


# ------------------------------------------------------------------ frequency
def frequency(df: pd.DataFrame) -> pd.Series:
    """Times each number 1-45 appeared as a winning number."""
    return pd.Series(indicator(df).sum(axis=0), index=NUMBERS, name="count")


def supp_frequency(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """Supplementary frequency, and how many draws in the window had supps recorded."""
    has = df[SUPP_COLS].notna().all(axis=1)
    sub = df[has]
    return pd.Series(indicator(sub, SUPP_COLS).sum(axis=0), index=NUMBERS, name="count"), int(has.sum())


# ------------------------------------------------------------------ hot / cold
def hot_cold(df: pd.DataFrame, lookbacks: tuple[int, ...] = (10, 25, 50)) -> pd.DataFrame:
    """Count over the last L draws vs expected L*6/45, as a binomial z-score.

    In one draw each number is a winner with probability p = 6/45, so its count
    over L draws has mean L*p and variance L*p*(1-p).
    """
    x = indicator(df)
    out = pd.DataFrame(index=NUMBERS)
    for lb in lookbacks:
        L = min(lb, len(df))
        count = x[-L:].sum(axis=0) if L else np.zeros(N)
        expected = L * P_IN_DRAW
        sd = np.sqrt(L * P_IN_DRAW * (1 - P_IN_DRAW)) if L else 1.0
        out[f"count_{lb}"] = count
        out[f"expected_{lb}"] = expected
        out[f"z_{lb}"] = (count - expected) / sd
    return out


# ------------------------------------------------------------------ gaps
def gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Draws since each number last appeared, and its average gap between appearances.

    current_gap = 0 means it was drawn in the latest draw. A number never seen in
    the window gets current_gap = number of draws and avg_gap = NaN.
    The expected gap for a fair draw is 45/6 = 7.5 draws.
    """
    x = indicator(df)
    n = len(df)
    current, avg, appearances = [], [], []
    for k in range(N):
        idx = np.flatnonzero(x[:, k])
        appearances.append(len(idx))
        current.append(n - 1 - idx[-1] if len(idx) else n)
        avg.append(float(np.diff(idx).mean()) if len(idx) > 1 else np.nan)
    out = pd.DataFrame(
        {"appearances": appearances, "current_gap": current, "avg_gap": avg}, index=NUMBERS
    )
    out["expected_gap"] = N / PICK
    # How overdue relative to the number's own rhythm (falls back to the fair rhythm).
    out["overdue_ratio"] = out["current_gap"] / out["avg_gap"].fillna(N / PICK)
    return out


# ------------------------------------------------------------------ pairs
def pair_matrix(df: pd.DataFrame) -> np.ndarray:
    """45x45 co-occurrence counts; [i-1, j-1] = draws containing both i and j. Diagonal = 0."""
    x = indicator(df)
    m = x.T @ x
    np.fill_diagonal(m, 0)
    return m


def expected_pair_count(n_draws: int) -> float:
    """Expected draws containing a specific pair: n * C(43,4)/C(45,6) = n * 30/1980."""
    return n_draws * (PICK * (PICK - 1)) / (N * (N - 1))


# ------------------------------------------------------------------ structure
def combo_structure(nums: np.ndarray) -> pd.DataFrame:
    """Structure of each 6-number row in a (k, 6) array (rows need not be sorted)."""
    a = np.sort(np.asarray(nums), axis=1)
    diffs = np.diff(a, axis=1) == 1
    # longest run of consecutive numbers
    run = np.ones(len(a), dtype=int)
    cur = np.ones(len(a), dtype=int)
    for j in range(diffs.shape[1]):
        cur = np.where(diffs[:, j], cur + 1, 1)
        run = np.maximum(run, cur)
    decade_idx = np.searchsorted([lo for lo, _ in DECADES], a, side="right") - 1
    # rows are sorted, so distinct decade groups = 1 + number of changes
    decade_groups = 1 + (np.diff(decade_idx, axis=1) != 0).sum(axis=1)
    odd = (a % 2 == 1).sum(axis=1)
    low = (a <= LOW_MAX).sum(axis=1)
    return pd.DataFrame(
        {
            "sum": a.sum(axis=1),
            "odd": odd,
            "even": PICK - odd,
            "low": low,
            "high": PICK - low,
            "consecutive_pairs": diffs.sum(axis=1),
            "longest_run": run,
            "decade_groups": decade_groups,
        }
    )


def structure(df: pd.DataFrame) -> pd.DataFrame:
    s = combo_structure(numbers_array(df))
    s.insert(0, "draw_date", df["draw_date"].to_numpy())
    return s


def structure_summary(df: pd.DataFrame) -> dict:
    s = structure(df)
    if s.empty:
        return {}
    decade_counts = np.zeros(len(DECADES), dtype=int)
    arr = numbers_array(df)
    for i, (lo, hi) in enumerate(DECADES):
        decade_counts[i] = ((arr >= lo) & (arr <= hi)).sum()
    return {
        "draws": len(s),
        "sum_mean": float(s["sum"].mean()),
        "sum_quantiles": {q: float(s["sum"].quantile(q)) for q in (0.05, 0.15, 0.5, 0.85, 0.95)},
        "odd_even": s["odd"].value_counts().reindex(range(7), fill_value=0).to_dict(),
        "low_high": s["low"].value_counts().reindex(range(7), fill_value=0).to_dict(),
        "consecutive_pairs": s["consecutive_pairs"].value_counts().sort_index().to_dict(),
        "decade_groups": s["decade_groups"].value_counts().sort_index().to_dict(),
        "decade_share": dict(zip(DECADE_LABELS, (decade_counts / decade_counts.sum()).round(4).tolist())),
    }


# ------------------------------------------------------------------ randomness
@dataclass
class ChiSquareResult:
    statistic: float
    dof: int
    p_value: float
    draws: int
    explanation: str


def randomness_check(df: pd.DataFrame) -> ChiSquareResult:
    """Chi-square goodness-of-fit of number frequencies against a uniform distribution."""
    obs = frequency(df).to_numpy()
    n = len(df)
    if n == 0:
        return ChiSquareResult(0.0, N - 1, 1.0, 0, "No draws in this window.")
    expected = np.full(N, obs.sum() / N)
    stat, p = stats.chisquare(obs, expected)
    return ChiSquareResult(float(stat), N - 1, float(p), n, explain_p_value(float(p), n))


def explain_p_value(p: float, n: int) -> str:
    pct = p * 100
    if p >= 0.05:
        verdict = (
            f"If the draw were perfectly fair, a spread of frequencies at least this uneven would "
            f"turn up about {pct:.0f}% of the time. That's ordinary: there's no evidence that any "
            f"number is favoured. The 'hot' and 'cold' numbers you see are what chance alone produces."
        )
    elif p >= 0.01:
        verdict = (
            f"A spread this uneven would turn up only about {pct:.1f}% of the time by chance. "
            f"That's mildly unusual, but checking 45 numbers across many windows will produce "
            f"results like this now and then. It isn't evidence of a bias that could be exploited."
        )
    else:
        verdict = (
            f"A spread this uneven would turn up less than 1% of the time by chance ({pct:.2f}%). "
            f"Worth noting, but with many windows and tests a rare result is still expected "
            f"occasionally; it doesn't make future draws predictable."
        )
    note = " With few draws in the window, this test has little power." if n < 100 else ""
    return verdict + note
