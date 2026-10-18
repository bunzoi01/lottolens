"""Build the read-only static copy (a PWA) for GitHub Pages.

Every link is relative, so the site works at https://<user>.github.io/<repo>/.
The service worker keeps the last copy on the phone for offline viewing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from datetime import datetime
from pathlib import Path

from . import paths
from .analysis.core import WINDOW_CHOICES
from .config import load_settings
from .data.dates import SYDNEY, now_sydney
from .data.db import Database
from .data.repo_state import export_draws
from .web.views import analysis_context, backtest_context, make_env, this_week_context

STATIC_ASSETS = [
    "app.css", "app.js", "analysis.js", "backtest.js", "history.js",
    "vendor/chart.umd.min.js",
    "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png",
]

MANIFEST = {
    "name": "LottoLens",
    "short_name": "LottoLens",
    "description": "Saturday Lotto statistics and weekly suggestions. For entertainment only.",
    "lang": "en-AU",
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "background_color": "#fcfcfb",
    "theme_color": "#2a78d6",
    "icons": [
        {"src": "static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SERVICE_WORKER = """// LottoLens service worker (generated). Pages: network first, falling back to the saved copy.
// Static files: from the cache, which is replaced whenever a new build is published.
const VERSION = "%(version)s";
const CACHE = "lottolens-" + VERSION;
const PRECACHE = %(precache)s;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("lottolens-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  const isPage = req.mode === "navigate" || /(\\/|\\.html|\\.csv|\\.webmanifest)$/.test(url.pathname);
  if (isPage) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || caches.match("index.html")))
    );
  } else {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
  }
});
"""


def _picks_csv(sset) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["target_draw_date", "rank", "n1", "n2", "n3", "n4", "n5", "n6", "score", "explanation", "seed"])
    for c in sset.combos if sset else []:
        w.writerow([sset.target_draw_date, c.rank, *c.numbers, c.score, c.explanation, sset.seed])
    return buf.getvalue()


def _compact_draws(db: Database) -> list:
    """[date, draw number, [winners], [supps] or None] per draw, newest first (small JSON)."""
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM draws ORDER BY draw_date DESC").fetchall()
    return [
        [r["draw_date"], r["draw_number"], [r[f"n{i}"] for i in range(1, 7)],
         [r["supp1"], r["supp2"]] if r["supp1"] is not None else None]
        for r in rows
    ]


def build_site(db: Database, out: Path, built_at: datetime | None = None) -> list[str]:
    """Render every page into `out` (replacing it). Returns the published file paths."""
    built_at = (built_at or now_sydney()).astimezone(SYDNEY)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    env = make_env(static_site=True)
    env.globals["built_at"] = built_at.strftime("%a %-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm") + " Sydney time"
    files: list[str] = []

    def write(rel: str, text: str) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        files.append(rel)

    def render(template: str, rel: str, active: str, **ctx) -> None:
        write(rel, env.get_template(template).render(active=active, refreshing=False, **ctx))

    week = this_week_context(db, weekly_only=True)
    render("this_week.html", "index.html", "this_week", **week)
    write("picks.csv", _picks_csv(week["sset"]))

    default_window = load_settings(db).window
    for w in WINDOW_CHOICES:
        ctx = analysis_context(db, w)
        render("analysis.html", f"analysis-{w}.html", "analysis", **ctx)
        if w == default_window:
            render("analysis.html", "analysis.html", "analysis", **ctx)

    render("history_static.html", "history.html", "history", draws=_compact_draws(db),
           count=db.draw_count(), latest=db.latest_draw_date())
    export_draws(db, out / "draws.csv")
    files.append("draws.csv")

    render("backtest.html", "backtest.html", "backtest", bt={"running": False, "error": None}, **backtest_context(db))

    for rel in STATIC_ASSETS:
        dest = out / "static" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths.STATIC_DIR / rel, dest)
        files.append(f"static/{rel}")

    write("manifest.webmanifest", json.dumps(MANIFEST, indent=2) + "\n")
    write("robots.txt", "User-agent: *\nDisallow: /\n")  # public, but keep it out of search engines
    write(".nojekyll", "")

    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode())
        digest.update((out / rel).read_bytes())
    precache = ["./"] + sorted(f for f in files if f not in (".nojekyll", "robots.txt"))
    write("sw.js", SERVICE_WORKER % {"version": digest.hexdigest()[:12], "precache": json.dumps(precache, indent=2)})
    return files
