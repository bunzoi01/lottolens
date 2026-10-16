"""Walk-forward backtest: algorithm vs random picks, using only data available at the time."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..algorithm.suggest import ALGO_VERSION, suggest, weekly_seed
from ..analysis.core import N, PICK, WIN_COLS
from ..config import Settings
from ..data.db import utcnow
from .prizes import DIVISIONS, any_prize_probability, division_probabilities, divisions_vec

log = logging.getLogger("lottolens.backtest")

RANDOM_BASELINE_SEED = 20_260_101


def score_games(games: np.ndarray, winners: np.ndarray, supps: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """games (k, 6); winners (6,); supps (2,) or None -> matches, supp matches, divisions (0 = none)."""
    win_mask = np.zeros(N + 1, dtype=bool)
    win_mask[winners] = True
    matches = win_mask[games].sum(axis=1)
    if supps is None:
        # Unknown supps: 5 matches scores as Div 3; Divs 2, 5 and 6 can't be awarded.
        return matches, np.full(len(games), -1), divisions_vec(matches, np.zeros(len(games)))
    supp_mask = np.zeros(N + 1, dtype=bool)
    supp_mask[supps] = True
    smatch = supp_mask[games].sum(axis=1)
    return matches, smatch, divisions_vec(matches, smatch)


def random_games(rng: np.random.Generator, n: int) -> np.ndarray:
    keys = rng.random((n, N))
    return np.argpartition(keys, PICK, axis=1)[:, :PICK] + 1


@dataclass
class BacktestResult:
    created_at: str
    algo_version: str
    params_hash: str
    draws: int
    combos_per_draw: int
    random_trials: int
    first_draw: str
    last_draw: str
    algo: dict  # totals for the algorithm
    random: dict  # averages over trials for random picks
    theory: dict  # exact expectation for any set of picks
    empirical_p: float  # share of random trials with at least as many prize-winning games
    per_draw: list[dict]
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_backtest(
    draws: pd.DataFrame,
    settings: Settings,
    n_draws: int = 104,
    random_trials: int = 200,
    progress: Callable[[int, int], None] | None = None,
) -> BacktestResult:
    draws = draws.sort_values("draw_date").reset_index(drop=True)
    n_draws = min(n_draws, len(draws) - 52)  # keep at least a year of history before the first test
    if n_draws <= 0:
        raise ValueError("not enough draws to backtest")
    k = settings.n_combos
    rng = np.random.default_rng(RANDOM_BASELINE_SEED)
    start = len(draws) - n_draws

    algo_div = np.zeros(7, dtype=int)
    algo_matches_total = 0
    rand_div = np.zeros((random_trials, 7), dtype=int)  # per-trial division counts
    rand_matches_total = 0.0
    per_draw = []
    algo_cum, rand_cum = 0, np.zeros(random_trials)

    for step, t in enumerate(range(start, len(draws))):
        row = draws.iloc[t]
        target = row["draw_date"]
        winners = row[WIN_COLS].to_numpy(dtype=int)
        has_supps = pd.notna(row.get("supp1")) and pd.notna(row.get("supp2"))
        supps = np.array([int(row["supp1"]), int(row["supp2"])]) if has_supps else None

        # Only draws strictly before the target are visible to the algorithm.
        s = suggest(draws.iloc[:t], target, settings, weekly_seed(target))
        games = np.array([c.numbers for c in s.combos])
        m, _, div = score_games(games, winners, supps)
        algo_div += np.bincount(div, minlength=7)
        algo_matches_total += int(m.sum())
        algo_wins = int((div > 0).sum())
        algo_cum += algo_wins

        rg = random_games(rng, random_trials * k)
        rm, _, rdiv = score_games(rg, winners, supps)
        rdiv = rdiv.reshape(random_trials, k)
        for d in range(1, 7):
            rand_div[:, d] += (rdiv == d).sum(axis=1)
        rand_matches_total += rm.mean() * k
        rand_wins = (rdiv > 0).sum(axis=1)
        rand_cum = rand_cum + rand_wins

        per_draw.append(
            {
                "draw_date": target.isoformat(),
                "algo_wins": algo_wins,
                "algo_best_matches": int(m.max()),
                "algo_cum": int(algo_cum),
                "random_mean_wins": float(rand_wins.mean()),
                "random_cum_mean": float(rand_cum.mean()),
                "random_cum_p05": float(np.percentile(rand_cum, 5)),
                "random_cum_p95": float(np.percentile(rand_cum, 95)),
            }
        )
        if progress:
            progress(step + 1, n_draws)

    games_total = n_draws * k
    probs = division_probabilities()
    algo_total_wins = int(algo_div[1:].sum())
    rand_trial_wins = rand_div[:, 1:].sum(axis=1)
    empirical_p = float((rand_trial_wins >= algo_total_wins).mean())

    algo = {
        "games": games_total,
        "prize_games": algo_total_wins,
        "prize_rate": algo_total_wins / games_total,
        "mean_matches": algo_matches_total / games_total,
        "divisions": {d: int(algo_div[d]) for d in DIVISIONS},
    }
    random = {
        "games": games_total,
        "prize_games": float(rand_trial_wins.mean()),
        "prize_games_p05": float(np.percentile(rand_trial_wins, 5)),
        "prize_games_p95": float(np.percentile(rand_trial_wins, 95)),
        "prize_rate": float(rand_trial_wins.mean() / games_total),
        "mean_matches": float(rand_matches_total / games_total),
        "divisions": {d: float(rand_div[:, d].mean()) for d in DIVISIONS},
    }
    theory = {
        "prize_games": games_total * any_prize_probability(),
        "prize_rate": any_prize_probability(),
        "mean_matches": PICK * PICK / N,
        "divisions": {d: games_total * probs[d] for d in DIVISIONS},
    }
    return BacktestResult(
        created_at=utcnow(),
        algo_version=ALGO_VERSION,
        params_hash=settings.params_hash(),
        draws=n_draws,
        combos_per_draw=k,
        random_trials=random_trials,
        first_draw=per_draw[0]["draw_date"],
        last_draw=per_draw[-1]["draw_date"],
        algo=algo,
        random=random,
        theory=theory,
        empirical_p=empirical_p,
        per_draw=per_draw,
        verdict=verdict_text(algo, random, empirical_p),
    )


def verdict_text(algo: dict, random: dict, p: float) -> str:
    a, r = algo["prize_games"], random["prize_games"]
    lo, hi = random["prize_games_p05"], random["prize_games_p95"]
    base = (
        f"LottoLens picks won a prize in {a} of {algo['games']} games. Random picks averaged {r:.1f} "
        f"(90% of random trials fell between {lo:.0f} and {hi:.0f})."
    )
    if 0.05 <= p <= 0.95:
        return base + (
            " That's no meaningful edge: the algorithm sits within what random picks normally do. "
            "This is the expected result. Every combination has exactly the same chance in every draw, "
            "and past results don't change future odds."
        )
    if p < 0.05:
        return base + (
            f" Only {p:.0%} of random trials did as well, so this period looks lucky. With this many "
            "draws and settings tried, a lucky stretch is expected now and then. It doesn't show that "
            "draws are predictable, and it isn't expected to continue."
        )
    return base + (
        " The algorithm did worse than most random trials over this period. That's also just chance: "
        "no set of picks is better or worse than another in the long run."
    )
