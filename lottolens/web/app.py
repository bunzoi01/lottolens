"""FastAPI app: server-rendered pages with HTMX partials. Bound to 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import threading
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import paths
from ..algorithm.store import current_set, load_set, regenerate, target_draw, weekly_set
from ..analysis.core import WINDOW_CHOICES
from ..backtest.walkforward import run_backtest
from ..config import DEFAULT_WEIGHTS, Settings, load_settings, save_settings
from ..data.dates import most_recent_draw_date, now_sydney
from ..data.db import Database
from ..data.importer import import_csv_text
from ..data.validate import DrawValidationError, make_draw
from ..fetch.service import is_stale
from ..pipeline import init_db, refresh_running, run_refresh
from .views import analysis_context, backtest_context, make_env, this_week_context

log = logging.getLogger("lottolens.web")

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
    templates = Jinja2Templates(env=make_env(static_site=False))

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        ctx.setdefault("active", name.split(".")[0])
        ctx.setdefault("refreshing", refresh_running())
        return templates.TemplateResponse(request, name, ctx)

    # ------------------------------------------------------------------ This Week
    @app.get("/", response_class=HTMLResponse)
    def this_week(request: Request):
        return render(request, "this_week.html", **this_week_context(get_db()))

    @app.post("/regenerate", response_class=HTMLResponse)
    def do_regenerate(request: Request):
        s = regenerate(get_db(), load_settings(get_db()))
        return render(request, "_combos.html", sset=s)

    @app.post("/weekly", response_class=HTMLResponse)
    def back_to_weekly(request: Request):
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
        return render(request, "analysis.html", **analysis_context(get_db(), window))

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
        return render(request, "backtest.html", bt=state["backtest"], **backtest_context(get_db()))

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
