"""The LottoLens Score: weighted sampling, structural filters, diverse top-10.

None of this can predict a lottery. Each draw is independent; the backtest
module measures this honestly against random picks.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..analysis.core import N, NUMBERS, PICK, apply_window, numbers_array
from ..analysis.metrics import combo_structure, expected_pair_count, frequency, gaps, hot_cold, pair_matrix
from ..config import Settings

ALGO_VERSION = "1.0"
FACTORS = ["frequency", "hot", "overdue", "pair", "random"]
_PAIRS = [(i, j) for i in range(PICK) for j in range(i + 1, PICK)]


@dataclass
class Combo:
    numbers: tuple[int, ...]
    score: float  # 0-100
    explanation: str
    hot: list[int] = field(default_factory=list)
    overdue: list[int] = field(default_factory=list)


@dataclass
class SuggestionSet:
    target_draw_date: date
    seed: int
    combos: list[Combo]
    data_through: date | None
    params: dict
    params_hash: str
    candidates: int
    passed_filters: int
    algo_version: str = ALGO_VERSION


def weekly_seed(target: date) -> int:
    """Stable seed for a draw date, so the week's picks don't change on reload."""
    return int(hashlib.sha256(f"LottoLens-weekly-{target.isoformat()}".encode()).hexdigest()[:15], 16)


def _minmax(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    lo, hi = np.nanmin(v), np.nanmax(v)
    if not np.isfinite(lo) or hi - lo < 1e-12:
        return np.full_like(v, 0.5)
    return np.nan_to_num((v - lo) / (hi - lo), nan=0.5)


@dataclass
class NumberModel:
    factors: pd.DataFrame  # index 1..45, columns FACTORS, each scaled 0-1
    raw: pd.DataFrame  # hot_z, overdue_ratio, frequency
    pair_norm: np.ndarray  # 45x45 pair lift scaled 0-1
    weights: dict[str, float]

    @property
    def number_weight(self) -> np.ndarray:
        return sum(self.weights[k] * self.factors[k].to_numpy() for k in FACTORS)


def build_model(history: pd.DataFrame, settings: Settings, rng: np.random.Generator) -> NumberModel:
    win = apply_window(history, settings.window)
    if len(win) < settings.hot_lookback:
        win = history  # too little data in the window; fall back to everything
    freq = frequency(win).to_numpy()
    hz = hot_cold(win, (settings.hot_lookback,))[f"z_{settings.hot_lookback}"].to_numpy()
    g = gaps(win)
    overdue = np.clip(g["overdue_ratio"].to_numpy(), 0, 3)
    lift = pair_matrix(win) / max(expected_pair_count(len(win)), 1e-9)
    off = ~np.eye(N, dtype=bool)
    pair_norm = np.zeros((N, N))
    pair_norm[off] = _minmax(lift[off])
    hot_f = _minmax(hz)
    # Pair affinity: how often a number has appeared alongside the currently hot numbers.
    pair_f = _minmax((pair_norm * hot_f[None, :]).sum(axis=1) / max(hot_f.sum(), 1e-9))
    factors = pd.DataFrame(
        {
            "frequency": _minmax(freq),
            "hot": hot_f,
            "overdue": _minmax(overdue),
            "pair": pair_f,
            "random": rng.random(N),
        },
        index=NUMBERS,
    )
    raw = pd.DataFrame({"hot_z": hz, "overdue_ratio": g["overdue_ratio"].to_numpy(), "frequency": freq}, index=NUMBERS)
    return NumberModel(factors, raw, pair_norm, settings.normalised_weights())


def sample_candidates(probs: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """n weighted samples of 6 distinct numbers (Gumbel top-k = sampling without replacement)."""
    keys = np.log(probs)[None, :] - np.log(-np.log(rng.random((n, N))))
    idx = np.argpartition(-keys, PICK, axis=1)[:, :PICK]
    combos = np.sort(idx + 1, axis=1)
    return np.unique(combos, axis=0)


def structure_mask(combos: np.ndarray, history: pd.DataFrame, settings: Settings) -> np.ndarray:
    s = combo_structure(combos)
    hist_sums = numbers_array(history).sum(axis=1)
    tail = (1 - settings.sum_central) / 2
    lo, hi = np.quantile(hist_sums, [tail, 1 - tail]) if len(hist_sums) else (0, 999)
    return (
        s["sum"].between(lo, hi)
        & s["odd"].between(settings.odd_min, settings.odd_max)
        & s["low"].between(settings.low_min, settings.low_max)
        & (s["longest_run"] <= settings.max_run)
        & (s["decade_groups"] >= settings.min_decades)
    ).to_numpy()


def score_combos(combos: np.ndarray, model: NumberModel) -> np.ndarray:
    """Weighted blend of each factor averaged over the combo; pair uses the combo's own 15 pairs."""
    idx = combos - 1
    score = np.zeros(len(combos))
    for k in FACTORS:
        if k == "pair":
            pair_vals = np.stack([model.pair_norm[idx[:, i], idx[:, j]] for i, j in _PAIRS], axis=1)
            score += model.weights[k] * pair_vals.mean(axis=1)
        else:
            score += model.weights[k] * model.factors[k].to_numpy()[idx].mean(axis=1)
    return score * 100


def select_diverse(combos: np.ndarray, scores: np.ndarray, k: int, max_overlap: int, max_uses: int) -> list[int]:
    """Greedy top-k by score: share at most `max_overlap` numbers, use each number at most `max_uses` times."""
    order = np.argsort(-scores, kind="stable")
    chosen: list[int] = []
    picked = np.zeros((0, N + 1), dtype=np.int8)
    uses = np.zeros(N + 1, dtype=int)
    for i in order:
        c = combos[i]
        if (uses[c] >= max_uses).any():
            continue
        if len(chosen) and picked[:, c].sum(axis=1).max() > max_overlap:
            continue
        chosen.append(int(i))
        row = np.zeros((1, N + 1), dtype=np.int8)
        row[0, c] = 1
        picked = np.vstack([picked, row])
        uses[c] += 1
        if len(chosen) == k:
            break
    return chosen


def explain(nums: tuple[int, ...], model: NumberModel, settings: Settings) -> tuple[str, list[int], list[int]]:
    hot = [n for n in nums if model.raw.loc[n, "hot_z"] >= settings.hot_z_threshold]
    overdue = [n for n in nums if model.raw.loc[n, "overdue_ratio"] >= settings.overdue_threshold]
    s = combo_structure(np.array([nums])).iloc[0]
    parts = []
    parts.append(f"{len(hot)} hot" if hot else "0 hot")
    parts.append(f"{len(overdue)} overdue")
    parts.append(f"sum {int(s['sum'])}")
    parts.append(f"{int(s['odd'])} odd/{int(s['even'])} even")
    parts.append(f"{int(s['low'])} low/{int(s['high'])} high")
    return ", ".join(parts), hot, overdue


def suggest(history: pd.DataFrame, target: date, settings: Settings, seed: int) -> SuggestionSet:
    """Generate suggestions for `target` from `history` (draws strictly before target only)."""
    history = history[history["draw_date"] < target].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    model = build_model(history, settings, rng)
    probs = 0.05 + model.number_weight
    probs = probs / probs.sum()

    total, passed_total = 0, 0
    chosen_combos: list[tuple[np.ndarray, float]] = []
    n = settings.n_candidates
    for _attempt in range(3):
        cands = sample_candidates(probs, n, rng)
        total += len(cands)
        cands = cands[structure_mask(cands, history, settings)]
        passed_total += len(cands)
        scores = score_combos(cands, model)
        picks = select_diverse(cands, scores, settings.n_combos, settings.max_overlap, settings.max_uses)
        chosen_combos = [(cands[i], float(scores[i])) for i in picks]
        if len(chosen_combos) == settings.n_combos:
            break
        n *= 2

    combos = []
    for arr, sc in chosen_combos:
        nums = tuple(int(x) for x in arr)
        text, hot, overdue = explain(nums, model, settings)
        combos.append(Combo(nums, round(sc, 2), text, hot, overdue))
    return SuggestionSet(
        target_draw_date=target,
        seed=seed,
        combos=combos,
        data_through=history["draw_date"].iloc[-1] if len(history) else None,
        params=settings.algorithm_params(),
        params_hash=settings.params_hash(),
        candidates=total,
        passed_filters=passed_total,
    )
