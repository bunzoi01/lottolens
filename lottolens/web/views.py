"""Page contexts and the Jinja environment, shared by the local server and the static site."""

from __future__ import annotations

from datetime import date

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import paths
from ..algorithm.store import current_set, load_set, target_draw, weekly_set
from ..analysis.core import WINDOW_CHOICES, apply_window
from ..analysis.metrics import (
    DECADE_LABELS,
    frequency,
    gaps,
    hot_cold,
    pair_matrix,
    randomness_check,
    structure,
    structure_summary,
    supp_frequency,
)
from ..backtest.prizes import DIVISION_LABELS, any_prize_probability, division
from ..backtest.tracking import live_history, live_totals
from ..config import load_settings
from ..data.dates import upcoming_draw_date
from ..data.db import Database
from ..fetch.base import THELOTT_VERIFY_URL

GAMBLING_HELP_URL = "https://www.gamblinghelponline.org.au"
GAMBLING_HELP_PHONE = "1800 858 858"

# Page name -> (server URL, static file)
PAGES = {
    "this_week": ("/", "index.html"),
    "analysis": ("/analysis", "analysis.html"),
    "history": ("/history", "history.html"),
    "backtest": ("/backtest", "backtest.html"),
    "settings": ("/settings", None),
}


def nicedate(d) -> str:
    if not d:
        return ""
    return (date.fromisoformat(d) if isinstance(d, str) else d).strftime("%a %-d %b %Y")


def make_env(static_site: bool = False) -> Environment:
    """Jinja environment. static_site=True renders relative links for the GitHub Pages copy."""
    env = Environment(loader=FileSystemLoader(paths.TEMPLATES_DIR), autoescape=select_autoescape(["html"]))

    def link(name: str) -> str:
        server, static = PAGES[name]
        return static if static_site else server

    def asset(path: str) -> str:
        return f"static/{path}" if static_site else f"/static/{path}"

    env.globals.update(
        static_site=static_site,
        link=link,
        asset=asset,
        gambling_help_url=GAMBLING_HELP_URL,
        gambling_help_phone=GAMBLING_HELP_PHONE,
        thelott_url=THELOTT_VERIFY_URL,
        division_labels=DIVISION_LABELS,
    )
    env.filters["nicedate"] = nicedate
    return env


# ---------------------------------------------------------------------- This Week
def last_draw_review(db: Database) -> dict | None:
    latest = db.latest_draw_date()
    if latest is None:
        return None
    draw = db.get_draw(latest)
    winners = {draw[f"n{i}"] for i in range(1, 7)}
    supps = {draw["supp1"], draw["supp2"]} if draw["supp1"] is not None else set()
    live = [h for h in live_history(db, limit=1) if h["draw_date"] == latest.isoformat()]
    if live:
        games, pre_draw = live[0]["games"], True
    else:
        stored = load_set(db, latest)
        if stored is None:
            games, pre_draw = [], None
        else:
            games = []
            for c in stored.combos:
                m = len(set(c.numbers) & winners)
                sm = len(set(c.numbers) & supps) if supps else None
                games.append({"numbers": list(c.numbers), "matches": m, "supp_matches": sm, "division": division(m, sm)})
            pre_draw = False
    return {"draw": draw, "winners": winners, "supps": supps, "games": games, "pre_draw": pre_draw}


def this_week_context(db: Database, weekly_only: bool = False) -> dict:
    settings = load_settings(db)
    s = weekly_set(db, settings) if weekly_only else current_set(db, settings)
    target = target_draw(db)
    upcoming = upcoming_draw_date()
    return dict(
        sset=s, target=target, upcoming=upcoming,
        stale=target is not None and target < upcoming,
        review=last_draw_review(db), live=live_totals(live_history(db)),
        odds_any=1 / any_prize_probability(),
    )


# ---------------------------------------------------------------------- Analysis
def analysis_context(db: Database, window: str | None = None) -> dict:
    settings = load_settings(db)
    window = window if window in WINDOW_CHOICES else settings.window
    all_df = db.draws_df()
    df = apply_window(all_df, window)
    freq = frequency(df)
    sfreq, supp_draws = supp_frequency(df)
    hc = hot_cold(df)
    g = gaps(df)
    pm = pair_matrix(df)
    st = structure(df)
    summary = structure_summary(df)
    chi = randomness_check(df)
    bins = list(range(20, 261, 10))
    hist, _ = np.histogram(st["sum"], bins=bins)
    triu = pm[np.triu_indices(45, 1)]
    top_pairs = sorted(
        ((int(pm[i, j]), i + 1, j + 1) for i in range(45) for j in range(i + 1, 45)), reverse=True
    )[:10]
    data = {
        "numbers": list(range(1, 46)),
        "freq": freq.tolist(),
        "expected_freq": len(df) * 6 / 45,
        "supp_freq": sfreq.tolist(),
        "supp_draws": supp_draws,
        "hot": {str(lb): hc[f"z_{lb}"].round(2).tolist() for lb in (10, 25, 50)},
        "hot_counts": {str(lb): hc[f"count_{lb}"].tolist() for lb in (10, 25, 50)},
        "current_gap": g["current_gap"].tolist(),
        "avg_gap": g["avg_gap"].round(2).fillna(0).tolist(),
        "pairs": pm.tolist(),
        "pair_max": int(triu.max()) if len(triu) else 0,
        "sum_bins": [f"{b}-{b + 9}" for b in bins[:-1]],
        "sum_hist": hist.tolist(),
        "odd": [summary.get("odd_even", {}).get(k, 0) for k in range(7)],
        "low": [summary.get("low_high", {}).get(k, 0) for k in range(7)],
        "decade_labels": DECADE_LABELS,
        "decade_share": list(summary.get("decade_share", {}).values()),
    }
    return dict(
        window=window, windows=list(WINDOW_CHOICES), draws=len(df),
        first=df["draw_date"].iloc[0] if len(df) else None, last=df["draw_date"].iloc[-1] if len(df) else None,
        data=data, chi=chi, summary=summary, top_pairs=top_pairs, total_draws=len(all_df),
    )


# ---------------------------------------------------------------------- Backtest
def backtest_context(db: Database) -> dict:
    result = db.kv_get("backtest:last")
    settings = load_settings(db)
    return dict(result=result, settings_changed=bool(result) and result["params_hash"] != settings.params_hash())
