"""FastAPI app: server-rendered pages with HTMX partials. Bound to 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime

import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import paths
from ..algorithm.store import current_set, load_set, regenerate, target_draw
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
from ..backtest.walkforward import run_backtest
from ..config import DEFAULT_WEIGHTS, Settings, load_settings, save_settings
from ..data.dates import most_recent_draw_date, now_sydney, upcoming_draw_date
from ..data.db import Database
from ..data.importer import import_csv_text
from ..data.validate import DrawValidationError, make_draw
from ..fetch.base import THELOTT_VERIFY_URL
from ..fetch.service import is_stale
from ..pipeline import init_db, refresh_running, run_refresh

log = logging.getLogger("lottolens.web")

GAMBLING_HELP_URL = "https://www.gamblinghelponline.org.au"
GAMBLING_HELP_PHONE = "1800 858 858"
CHECK_INTERVAL_S = 3600


def create_app(db: Database | None = None, background: bool = True) -> FastAPI:
    paths.setup_logging()
    state: dict = {"db": db, "backtest": {"running": False, "done": 0, "total": 0, "error": None}}

    def get_db() -> Database:
        return state["db"]

    async def refresh_loop():
        while True:
            try:
                if is_stale(get_db()):
                    log.info("latest stored draw is older than the most recent draw; refreshing")
                    await asyncio.to_thread(run_refresh, get_db())
            except Exception:
                log.exception("background refresh check failed")
            await asyncio.sleep(CHECK_INTERVAL_S)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["db"] = init_db(state["db"])
        task = asyncio.create_task(refresh_loop()) if background else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="LottoLens", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=paths.STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=paths.TEMPLATES_DIR)
    templates.env.globals.update(
        gambling_help_url=GAMBLING_HELP_URL,
        gambling_help_phone=GAMBLING_HELP_PHONE,
        thelott_url=THELOTT_VERIFY_URL,
        division_labels=DIVISION_LABELS,
    )
    templates.env.filters["nicedate"] = lambda d: (
        (date.fromisoformat(d) if isinstance(d, str) else d).strftime("%a %-d %b %Y") if d else ""
    )

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        ctx.setdefault("active", name.split(".")[0])
        ctx.setdefault("refreshing", refresh_running())
        return templates.TemplateResponse(request, name, ctx)

    # ------------------------------------------------------------------ This Week
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

    @app.get("/", response_class=HTMLResponse)
    def this_week(request: Request):
        db = get_db()
        settings = load_settings(db)
        s = current_set(db, settings)
        target = target_draw(db)
        upcoming = upcoming_draw_date()
        history = live_history(db)
        return render(
            request, "this_week.html",
            sset=s, target=target, upcoming=upcoming,
            stale=target is not None and target < upcoming,
            review=last_draw_review(db), live=live_totals(history),
            odds_any=1 / any_prize_probability(),
        )

    @app.post("/regenerate", response_class=HTMLResponse)
    def do_regenerate(request: Request):
        s = regenerate(get_db(), load_settings(get_db()))
        return render(request, "_combos.html", sset=s)

    @app.post("/weekly", response_class=HTMLResponse)
    def back_to_weekly(request: Request):
        from ..algorithm.store import weekly_set

        return render(request, "_combos.html", sset=weekly_set(get_db(), load_settings(get_db())))

    @app.get("/export.csv")
    def export_csv(seed: int | None = None):
        db = get_db()
        target = target_draw(db)
        s = load_set(db, target, seed=seed) if seed is not None else current_set(db, load_settings(db))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["target_draw_date", "rank", "n1", "n2", "n3", "n4", "n5", "n6", "score", "explanation", "seed", "kind"])
        for c in s.combos if s else []:
            w.writerow([s.target_draw_date, c.rank, *c.numbers, c.score, c.explanation, s.seed, s.kind])
        name = f"lottolens_{target}.csv"
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ Analysis
    @app.get("/analysis", response_class=HTMLResponse)
    def analysis(request: Request, window: str | None = None):
        db = get_db()
        settings = load_settings(db)
        window = window if window in WINDOW_CHOICES else settings.window
        df = apply_window(db.draws_df(), window)
        all_df = db.draws_df()
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
        return render(
            request, "analysis.html", window=window, windows=list(WINDOW_CHOICES), draws=len(df),
            first=df["draw_date"].iloc[0] if len(df) else None, last=df["draw_date"].iloc[-1] if len(df) else None,
            data=data, chi=chi, summary=summary, top_pairs=top_pairs, total_draws=len(all_df),
        )

    # ------------------------------------------------------------------ History
    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, q: str = "", page: int = 1):
        db = get_db()
        rows, total = db.search_draws(q, page)
        ctx = dict(rows=rows, total=total, q=q, page=page, pages=max(1, -(-total // 25)))
        if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "draw-table":
            return render(request, "_draw_table.html", **ctx)
        return render(
            request, "history.html", **ctx, discrepancies=db.discrepancies(), log_rows=db.recent_log(30),
            latest=db.latest_draw_date(), count=db.draw_count(), most_recent=most_recent_draw_date(),
        )

    @app.get("/history/log", response_class=HTMLResponse)
    def history_log(request: Request):
        return render(request, "_log.html", log_rows=get_db().recent_log(30))

    @app.post("/history/fetch", response_class=HTMLResponse)
    def fetch_latest(request: Request):
        db = get_db()
        if refresh_running():
            db.log("A refresh is already running.", "WARNING")
        else:
            threading.Thread(target=run_refresh, args=(db,), daemon=True).start()
            db.log("Fetch started from the History page.")
        return render(request, "_log.html", log_rows=db.recent_log(30), refreshing=True)

    @app.post("/history/import", response_class=HTMLResponse)
    async def import_upload(request: Request, file: UploadFile = File(...)):
        db = get_db()
        text = (await file.read()).decode("utf-8", errors="replace")
        report = import_csv_text(db, text, source="csv-upload")
        db.log(f"CSV upload {file.filename}: {report}", "WARNING" if report.errors else "INFO")
        if report.stats.inserted or report.stats.updated:
            run_refresh(db, fetch=False)
        return render(request, "_message.html", ok=not report.errors, message=str(report), details=report.errors[:20])

    @app.post("/history/manual", response_class=HTMLResponse)
    def manual_entry(
        request: Request,
        draw_date: str = Form(...),
        numbers: str = Form(...),
        supps: str = Form(""),
        draw_number: str = Form(""),
    ):
        db = get_db()
        try:
            nums = [int(x) for x in numbers.replace(",", " ").split()]
            sup = [int(x) for x in supps.replace(",", " ").split()] or None
            d = make_draw(draw_date, nums, sup, draw_number=int(draw_number) if draw_number.strip() else None,
                          source="manual")
        except (ValueError, DrawValidationError) as exc:
            return render(request, "_message.html", ok=False, message=str(exc), details=[])
        stats = db.upsert_draws([d])
        db.log(f"Manual entry {d.draw_date}: {stats}", "WARNING" if stats.conflicts else "INFO")
        if stats.conflicts:
            msg = "That draw is already stored with different numbers. It's flagged for review below; nothing was overwritten."
            return render(request, "_message.html", ok=False, message=msg, details=[])
        run_refresh(db, fetch=False)
        return render(request, "_message.html", ok=True, message=f"Saved {d.draw_date}: {stats}.", details=[])

    @app.post("/discrepancy/{disc_id}/{action}")
    def resolve(disc_id: int, action: str):
        db = get_db()
        disc = next((x for x in db.discrepancies() if x["id"] == disc_id), None)
        if disc and action == "accept" and disc["field"] in ("numbers", "supps"):
            row = db.get_draw(date.fromisoformat(disc["draw_date"]))
            nums = disc["incoming"] if disc["field"] == "numbers" else [row[f"n{i}"] for i in range(1, 7)]
            sup = disc["incoming"] if disc["field"] == "supps" else (
                [row["supp1"], row["supp2"]] if row["supp1"] is not None else None)
            db.replace_draw(make_draw(disc["draw_date"], nums, sup, row["draw_number"], disc["incoming_source"] + "(accepted)"))
            db.log(f"Discrepancy {disc['draw_date']}: accepted {disc['incoming_source']} value.", "WARNING")
            run_refresh(db, fetch=False)
        elif disc:
            db.resolve_discrepancy(disc_id)
            db.log(f"Discrepancy {disc['draw_date']}: kept stored value.")
        return RedirectResponse("/history", status_code=303)

    # ------------------------------------------------------------------ Backtest
    @app.get("/backtest", response_class=HTMLResponse)
    def backtest_page(request: Request):
        db = get_db()
        result = db.kv_get("backtest:last")
        settings = load_settings(db)
        return render(request, "backtest.html", result=result, bt=state["backtest"],
                      settings_changed=bool(result) and result["params_hash"] != settings.params_hash())

    def _run_backtest(n_draws: int, trials: int):
        bt = state["backtest"]
        db = get_db()
        try:
            def progress(done, total):
                bt["done"], bt["total"] = done, total
            res = run_backtest(db.draws_df(), load_settings(db), n_draws=n_draws, random_trials=trials, progress=progress)
            db.kv_set("backtest:last", res.to_dict())
            db.log(f"Backtest finished: {res.algo['prize_games']} prize games vs random {res.random['prize_games']:.1f}.")
        except Exception as exc:
            log.exception("backtest failed")
            bt["error"] = str(exc)
        finally:
            bt["running"] = False

    @app.post("/backtest/run", response_class=HTMLResponse)
    def backtest_run(request: Request, n_draws: int = Form(104), trials: int = Form(200)):
        bt = state["backtest"]
        if not bt["running"]:
            bt.update(running=True, done=0, total=n_draws, error=None)
            threading.Thread(target=_run_backtest, args=(max(10, min(n_draws, 1000)), max(200, min(trials, 2000))),
                             daemon=True).start()
        return render(request, "_backtest_progress.html", bt=bt)

    @app.get("/backtest/status", response_class=HTMLResponse)
    def backtest_status(request: Request):
        bt = state["backtest"]
        if not bt["running"]:
            return Response(headers={"HX-Refresh": "true"})
        return render(request, "_backtest_progress.html", bt=bt)

    # ------------------------------------------------------------------ Settings
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: int = 0):
        return render(request, "settings.html", s=load_settings(get_db()), windows=list(WINDOW_CHOICES),
                      defaults=Settings(), saved=saved, weight_names=list(DEFAULT_WEIGHTS))

    @app.post("/settings")
    async def settings_save(request: Request):
        form = await request.form()
        if form.get("reset"):
            s = Settings()
        else:
            s = load_settings(get_db())
            s.window = form.get("window", s.window) if form.get("window") in WINDOW_CHOICES else s.window
            s.weights = {k: float(form.get(f"w_{k}", s.weights[k] * 100)) / 100 for k in DEFAULT_WEIGHTS}
            for name in ("hot_lookback", "n_candidates", "odd_min", "odd_max", "low_min", "low_max",
                         "max_run", "min_decades", "max_overlap", "max_uses"):
                if form.get(name):
                    setattr(s, name, int(form[name]))
            for name in ("sum_central", "hot_z_threshold", "overdue_threshold"):
                if form.get(name):
                    setattr(s, name, float(form[name]))
            s.n_candidates = max(50_000, min(s.n_candidates, 500_000))
            s.hot_lookback = max(5, min(s.hot_lookback, 200))
            s.sum_central = max(0.3, min(s.sum_central, 1.0))
            s.lottonumbers_enabled = form.get("lottonumbers_enabled") == "on"
        save_settings(get_db(), s)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/healthz")
    def healthz():
        db = get_db()
        return {"ok": True, "draws": db.draw_count(), "latest": str(db.latest_draw_date()), "now": now_sydney().isoformat()}

    return app
