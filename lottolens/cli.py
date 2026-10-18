"""Command line: python -m lottolens refresh | suggest | backtest | import <csv> | serve | publish | cloud"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

HOST = "127.0.0.1"  # never 0.0.0.0: the app is for this Mac only
PORT = 8765


def _db():
    from .pipeline import init_db

    return init_db()


def cmd_refresh(args) -> int:
    from .pipeline import run_refresh
    from .scheduler.notify import notify

    db = _db()
    if args.scheduled:
        from .scheduler.gate import should_run_scheduled

        ok, why = should_run_scheduled(db)
        if not ok:
            print(f"skipped: {why}")
            return 0
    rep = run_refresh(db, full=args.full)
    print(rep.summary())
    if args.notify and rep.new_draws and rep.target:
        notify("LottoLens", f"New result stored. Suggestions for {rep.target:%a %d %b} are ready.")
    return 1 if rep.errors else 0


def cmd_suggest(args) -> int:
    from .algorithm.store import current_set, regenerate
    from .config import load_settings

    db = _db()
    settings = load_settings(db)
    s = regenerate(db, settings) if args.regenerate else current_set(db, settings)
    if s is None:
        print("No draws stored yet.")
        return 1
    print(f"Suggestions for {s.target_draw_date:%a %d %b %Y} ({s.kind}, seed {s.seed}). For entertainment only.")
    for c in s.combos:
        print(f"{c.rank:>2}. {' '.join(f'{n:>2}' for n in c.numbers)}   {c.explanation}")
    return 0


def cmd_backtest(args) -> int:
    from .backtest.walkforward import run_backtest
    from .config import load_settings

    db = _db()

    def progress(done, total):
        print(f"\r  draw {done}/{total}", end="", file=sys.stderr, flush=True)

    res = run_backtest(db.draws_df(), load_settings(db), n_draws=args.draws, random_trials=args.trials, progress=progress)
    print(file=sys.stderr)
    db.kv_set("backtest:last", res.to_dict())
    print(res.verdict)
    return 0


def cmd_import(args) -> int:
    from .data.importer import import_csv_file
    from .pipeline import run_refresh

    db = _db()
    rep = import_csv_file(db, args.csv, source="csv-cli")
    print(rep)
    for e in rep.errors[:50]:
        print("  ", e)
    run_refresh(db, fetch=False)
    return 1 if rep.errors else 0


def cmd_publish(args) -> int:
    from pathlib import Path

    from .site import build_site

    files = build_site(_db(), Path(args.out))
    print(f"Static site written to {args.out} ({len(files)} files). Preview: python -m http.server -d {args.out}")
    return 0


def cmd_cloud(args) -> int:
    from pathlib import Path

    from .cloud import run_cloud

    rep = run_cloud(Path(args.data), Path(args.out), fetch=not args.no_fetch)
    print(rep.markdown())
    return 0  # errors are reported as warnings; the existing data still gets published


def cmd_serve(args) -> int:
    import threading

    import uvicorn

    from .web.app import create_app

    url = f"http://{HOST}:{args.port}"
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"LottoLens running at {url} (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=HOST, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    from . import paths

    paths.setup_logging()
    p = argparse.ArgumentParser(prog="lottolens", description="Saturday Lotto statistics. For entertainment only.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="fetch new results, score last week, build next suggestions")
    r.add_argument("--full", action="store_true", help="re-walk every yearly archive (cached pages are reused)")
    r.add_argument("--notify", action="store_true", help="macOS notification when new suggestions are ready")
    r.add_argument("--scheduled", action="store_true", help="only run in the Sunday/Monday 10:00 Sydney windows")
    r.set_defaults(func=cmd_refresh)

    s = sub.add_parser("suggest", help="print this week's suggestions")
    s.add_argument("--regenerate", action="store_true", help="use a fresh random seed")
    s.set_defaults(func=cmd_suggest)

    b = sub.add_parser("backtest", help="walk-forward backtest against random picks")
    b.add_argument("--draws", type=int, default=104)
    b.add_argument("--trials", type=int, default=200)
    b.set_defaults(func=cmd_backtest)

    i = sub.add_parser("import", help="import a CSV of draws")
    i.add_argument("csv")
    i.set_defaults(func=cmd_import)

    pb = sub.add_parser("publish", help="build the read-only static site (PWA) from the local database")
    pb.add_argument("--out", default="_site")
    pb.set_defaults(func=cmd_publish)

    c = sub.add_parser("cloud", help="weekly GitHub Actions run: data/ -> refresh -> data/ + static site")
    c.add_argument("--data", default="data")
    c.add_argument("--out", default="_site")
    c.add_argument("--no-fetch", action="store_true", help="skip fetching (rebuild from data/ only)")
    c.set_defaults(func=cmd_cloud)

    v = sub.add_parser("serve", help="run the web UI on 127.0.0.1")
    v.add_argument("--port", type=int, default=PORT)
    v.add_argument("--open", action="store_true", help="open the browser")
    v.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception:
        logging.getLogger("lottolens").exception("command failed")
        raise
