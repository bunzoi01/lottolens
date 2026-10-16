"""Shared helpers: windows and the draw/number indicator matrix.

Every analysis function takes a draws DataFrame (oldest first) with columns
draw_date, n1..n6 and optionally supp1, supp2. Nothing here imports web code.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

N = 45
PICK = 6
NUMBERS = np.arange(1, N + 1)
WIN_COLS = [f"n{i}" for i in range(1, PICK + 1)]
SUPP_COLS = ["supp1", "supp2"]
P_IN_DRAW = PICK / N  # chance a given number is among the 6 winners in one draw

WINDOW_CHOICES = {"1": 1, "2": 2, "5": 5, "10": 10, "all": None}
DEFAULT_WINDOW = "2"


def apply_window(df: pd.DataFrame, years: int | str | None, as_of: date | None = None) -> pd.DataFrame:
    """Draws within the last `years` years up to `as_of` (default: latest draw)."""
    if isinstance(years, str):
        years = WINDOW_CHOICES[years]
    if df.empty:
        return df
    as_of = as_of or df["draw_date"].iloc[-1]
    out = df[df["draw_date"] <= as_of]
    if years is None:
        return out.reset_index(drop=True)
    try:
        start = as_of.replace(year=as_of.year - years)
    except ValueError:  # 29 Feb
        start = as_of.replace(year=as_of.year - years, day=28)
    return out[out["draw_date"] > start].reset_index(drop=True)


def numbers_array(df: pd.DataFrame) -> np.ndarray:
    """(draws, 6) int array of winning numbers."""
    return df[WIN_COLS].to_numpy(dtype=np.int64)


def indicator(df: pd.DataFrame, cols: list[str] = WIN_COLS) -> np.ndarray:
    """(draws, 45) 0/1 matrix: X[d, k-1] = 1 if number k was drawn in draw d.

    Rows with missing values in `cols` (e.g. old draws without supps) are all-zero.
    """
    vals = df[cols].astype("float64").to_numpy()
    x = np.zeros((len(df), N), dtype=np.int64)
    rows, cs = np.nonzero(~np.isnan(vals))
    x[rows, vals[rows, cs].astype(np.int64) - 1] = 1
    return x
