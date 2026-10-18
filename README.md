# LottoLens

A local statistical analysis and entertainment tool for Australian Saturday Lotto. It runs on your
Mac at <http://127.0.0.1:8765>. It analyses every Saturday Lotto draw since 30 August 1986 and
suggests 10 games each week.

> **For entertainment only.** Lotto draws are independent random events. Past results can't predict
> future draws, and every combination has the same 1 in 8,145,060 chance of Division 1 in every
> draw. LottoLens is not a predictor. Its own backtest shows it has no edge over random picks.
> If gambling is causing you harm, contact [Gambling Help Online](https://www.gamblinghelponline.org.au)
> or call **1800 858 858** (free, 24/7).

## Setup and run

Requirements: macOS, plus either [uv](https://docs.astral.sh/uv/) (recommended) or Python 3.12. No
API keys or paid services.

```sh
./run.sh            # creates the environment if needed, starts the server and opens the browser
./test.sh           # runs the test suite (offline; never touches your real data)
```

The virtualenv lives in `~/Library/Application Support/LottoLens/venv`, not in this folder, so
OneDrive doesn't sync thousands of package files. Don't run a bare `uv run` or `uv sync` here:
that recreates `.venv` in the project folder. Use the scripts, or set
`UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/LottoLens/venv"` first.

| What | Where |
|---|---|
| Database (SQLite) | `~/Library/Application Support/LottoLens/lotto.db` |
| HTTP cache | `~/Library/Application Support/LottoLens/cache/` |
| Logs | `~/Library/Logs/LottoLens/` |

The server binds to `127.0.0.1` only, never `0.0.0.0`.

### Command line

```sh
PY="$HOME/Library/Application Support/LottoLens/venv/bin/python"
"$PY" -m lottolens refresh            # fetch new results, score last week's picks, build next week's
"$PY" -m lottolens refresh --full     # re-walk every yearly archive (cached pages are reused)
"$PY" -m lottolens suggest            # print this week's 10 games (--regenerate for a fresh seed)
"$PY" -m lottolens backtest           # walk-forward backtest (--draws 104 --trials 200)
"$PY" -m lottolens import file.csv    # import draws from a CSV
"$PY" -m lottolens serve              # run the web UI (--open to open the browser)
"$PY" -m lottolens publish            # build the read-only phone site into _site/
"$PY" -m lottolens cloud              # what the weekly GitHub Actions run does
```

## iPhone app (GitHub Pages)

A read-only copy of LottoLens is published to GitHub Pages every week, so it works on your phone
anywhere, on Wi-Fi or mobile data, with your Mac switched off:

**<https://bunzoi01.github.io/lottolens/>**

To install it: open the link in **Safari**, tap **Share**, then **Add to Home Screen**. It opens
full-screen like an app. It also keeps the last copy it loaded, so you can still see this week's
picks with no signal.

How it stays up to date: `.github/workflows/weekly-update.yml` runs on GitHub's servers every
Sunday at 10:00 Sydney time, with a Monday retry. Each run:

1. rebuilds a database from `data/draws.csv`, `data/suggestions.csv` and `data/backtest.json`;
2. fetches only the new result from au.lottonumbers.com (same polite rules as the Mac app);
3. scores last week's picks, builds next week's, and re-runs the backtest;
4. commits the updated `data/` files back to the repo;
5. publishes the site.

The workflow also runs when code is pushed, and you can start it by hand from the **Actions** tab.

| | Phone (GitHub Pages) | Mac app |
|---|---|---|
| Works with the Mac off | Yes | No |
| This Week, Analysis, History, Backtest | Yes (read-only) | Yes |
| Regenerate, Settings, Fetch, CSV import, manual entry | No | Yes |
| Who can see it | **Anyone with the link** (public). It asks search engines not to index it. | Only this Mac |

Because the workflow commits to `main` each week, run `git pull` before you push your own changes.
To rebuild the site from your Mac's database instead, run
`python -m lottolens publish --out _site` and preview it with
`python -m http.server -d _site`.

## Weekly refresh

- **While the app is running:** it checks on startup and then hourly. If the latest stored draw is
  older than the most recent Saturday draw (Australia/Sydney time, results treated as available
  from 9 pm), it fetches.
- **When the app isn't running:** install the launchd job.

```sh
./install_schedule.sh     # installs ~/Library/LaunchAgents/au.lottolens.refresh.plist
./uninstall_schedule.sh   # removes it
```

launchd wakes the job hourly at :05. The job only acts on **Sunday from 10:00 Sydney time**, with
one **Monday 10:00 retry**, and only when a result is missing. That check happens in Python, so it's
correct through daylight-saving changes and whatever time zone your Mac uses. When new suggestions
are ready, it shows a macOS notification through `osascript`. Its output goes to
`~/Library/Logs/LottoLens/launchd.*.log`.

## Data sources

- **Seed:** `data/saturday_lotto_history.csv` (2,053 draws, 1986-08-30 to 2025-12-27). It's
  imported on first run.
- **au.lottonumbers.com** is the automatic source. It uses the yearly archive pages
  (`/saturday-lotto/results/{year}-archive`) and the latest-results page. On first run, every
  archive from 1986 is read once. This adds supplementaries and draw numbers to the seed rows,
  cross-checks the winning numbers (all 2,053 seed draws matched) and back-fills 2026. After that,
  only draws newer than the latest stored one are fetched.
- **Fetching rules:** robots.txt is checked (and fetching stops if a page is disallowed), the
  User-Agent is descriptive, there's at most 1 request every 2 seconds, and pages are cached (past
  years forever, the current year for 30 minutes).
- **thelott.com is a manual cross-check.** Its results page loads data in the browser, and its JSON
  API blocks automated clients (HTTP 403). The app links to it instead. If a manual entry or CSV
  import disagrees with a stored draw, the disagreement is flagged on the History page, and nothing
  is silently overwritten.
- **Fallbacks:** CSV import and manual entry, both on the History page.

Every draw is validated: 6 unique numbers from 1–45, 2 supplementaries distinct from the winners,
and a valid draw date. A valid date is a Saturday, or the New Year exception. When 1 January falls
on a Saturday, the draw has usually moved to Friday 31 December (1999, 2004, 2010, 2021); in 1994
it stayed on Saturday 1 January.

## How the suggestions work ("LottoLens Score")

1. **Number weights.** Each number from 1 to 45 gets a weight that blends five factors. Each factor
   is scaled to 0–1 over the analysis window (default: last 2 years). All weights are adjustable in
   Settings.

   | Factor | Default weight | Measures |
   |---|---|---|
   | Long-run frequency | 30% | how often the number was drawn |
   | Recent hotness | 25% | z-score of its count over the last 25 draws vs the expected 6/45 per draw |
   | Overdue | 20% | draws since it last appeared ÷ its average gap |
   | Pair affinity | 15% | how often it appeared alongside the currently hot numbers |
   | Random | 10% | seeded noise |
2. **Candidates.** 50,000 candidate games are drawn by weighted sampling without replacement
   (vectorised with the Gumbel top-k method).
3. **Filters.** Candidates must match the common structure of past winning sets:
   - the sum falls in the central 70% of historical sums;
   - 2–4 odd numbers and 2–4 low numbers (1–22);
   - no run of 3 or more consecutive numbers ("at most 2 consecutive");
   - at least 3 of the 5 decade groups.
4. **Score and diversity.** Each game's score is the weighted average of its numbers' factors; the
   pair factor uses the game's own 15 pairs. The top 10 are picked greedily, so that no two games
   share more than 2 numbers and no number appears in more than 3 games.
5. **Determinism.** The seed comes from the target draw date, so the week's picks stay the same
   until a new result is stored. **Regenerate** uses a fresh random seed. Every set is stored with
   its seed, settings fingerprint, algorithm version, the date its data runs to, and when it was
   made.

The score only measures how closely a game matches your chosen weighting. It isn't a probability of
winning.

## How to read the backtest

For each of the last N draws (default 104), LottoLens builds 10 games using only the draws before
that date. Those games are scored against the actual result using the Saturday Lotto prize
divisions:

| Division | Needs |
|---|---|
| 1 | 6 winning numbers |
| 2 | 5 + a supplementary |
| 3 | 5 |
| 4 | 4 |
| 5 | 3 + a supplementary |
| 6 | 1 or 2 + both supplementaries |

The same draws are also played by 200 independent sets of 10 random games each. The chart shows
LottoLens against the random average and the band holding the middle 90% of random trials. The
table adds the exact expected count from the odds: about 1 prize-winning game in 85.

**What you should see is no meaningful edge.** On the real data (Oct 2024 to Oct 2026), LottoLens
won a prize in 14 of 1,040 games. Random picks averaged 12.0, and 34% of random trials did as well
or better. That's ordinary luck. A result above or below the band in some period is also luck,
because it doesn't carry over to future draws.

**Live tracking:** after each new result, any stored suggestions for that draw are scored. Only sets
made *before* the draw count as live picks.

## Project layout

```
lottolens/
  data/       SQLite storage, validation, CSV import, Sydney draw-date logic
  fetch/      polite HTTP client, ResultsProvider, au.lottonumbers.com parser, back-fill
  analysis/   frequency, hot/cold, gaps, pairs, structure, chi-square (no web dependencies)
  algorithm/  weights, sampling, filters, diversity, storage
  backtest/   prize divisions, walk-forward backtest, live tracking
  scheduler/  Sydney-time gate for launchd, macOS notifications
  web/        FastAPI app (HTMX + Chart.js, vendored in static/vendor)
  site.py     static PWA build for GitHub Pages; cloud.py = the weekly Actions run
  cli.py, pipeline.py, config.py, paths.py
.github/workflows/weekly-update.yml   weekly cloud update + Pages deploy
data/       draws.csv, suggestions.csv, backtest.json (updated weekly by the workflow)
templates/  static/  tests/ (fixtures = saved HTML pages)  data/
```
