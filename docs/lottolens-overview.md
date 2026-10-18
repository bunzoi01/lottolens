# LottoLens overview

This page explains what LottoLens is, how it works, where its data comes from and how to open it.
The [README](../README.md) has the full setup and command reference.

> **For entertainment only.** Lotto draws are independent random events. Past results can't predict
> future draws, and every combination has the same 1 in 8,145,060 chance of Division 1 in every
> draw. LottoLens is a statistical analysis tool, not a predictor.
> If gambling is causing you harm, contact [Gambling Help Online](https://www.gamblinghelponline.org.au)
> or call **1800 858 858** (free, 24/7).

## What it is

LottoLens is a small application that runs on a Mac. It keeps every Australian Saturday Lotto result
since 30 August 1986 in a local database, and it does three things with them:

- **Analysis:** charts how often each number has been drawn, which numbers are "hot" or "cold" right
  now, how long since each number last appeared, which pairs turn up together, and what winning sets
  typically look like (sum, odd/even, low/high, spread). It also runs a statistical test of whether
  the results look fair, and explains the answer in plain English.
- **Suggestions:** each week it suggests 10 six-number games, each with a one-line explanation
  (for example "2 hot, 1 overdue, sum 138, 3 odd/3 even").
- **An honesty check:** it backtests its own suggestions against random picks over the past two
  years, and tracks how each week's suggestions do once the result is in. As expected for a random
  game, it shows no real edge. The app says so plainly.

Everything runs locally. There are no accounts, no paid services and no API keys. The app is only
reachable from the Mac it runs on.

## How it works

### Each week

```
Saturday night draw
      │
      ▼
Fetch the new result  ──►  Score last week's suggestions against it
      │
      ▼
Build next week's 10 suggestions  ──►  Show them in the browser (and a macOS notification)
```

The weekly update runs in the cloud. Every Sunday at 10:00 Sydney time, with a Monday retry, a
GitHub Actions job fetches the result, builds the new picks and publishes the phone version, so it
doesn't depend on your Mac. On the Mac, the full app also checks for new results when it starts and
every hour while it's running, and an optional background job can do the same on Sunday mornings.
All times are Sydney time, including daylight saving.

### How the 10 suggestions are chosen

1. **Weight every number from 1 to 45.** Each number gets a weight that blends five factors. The
   weights can be changed in Settings.

   | Factor | Default weight | Measures |
   |---|---|---|
   | Long-run frequency | 30% | how often the number was drawn |
   | Recent hotness | 25% | how often it was drawn in the last 25 draws, compared with what chance predicts |
   | Overdue | 20% | how long since it last appeared, relative to its usual gap |
   | Pair affinity | 15% | how often it has appeared alongside the currently hot numbers |
   | Random | 10% | a random element |
2. **Generate 50,000 candidate games**, favouring the higher-weighted numbers.
3. **Keep only "typical-looking" games.** A game stays in if:
   - its sum is in the usual range;
   - it has a balanced mix of odd/even and low/high numbers;
   - it has no long runs of consecutive numbers;
   - its numbers spread across at least 3 decade groups.
4. **Pick the 10 best-scoring games that are also varied.** No two games share more than 2 numbers,
   and no number is used in more than 3 games.
5. **Keep them fixed for the week.** The picks are tied to the draw date, so they stay the same all
   week and change automatically once the next result arrives. A **Regenerate** button produces a
   fresh set on request.

None of this changes the odds. Every game has the same chance of winning whichever numbers are
chosen. The backtest shows this directly: over 104 recent draws, LottoLens won a prize in 14 of
1,040 games, while random picks averaged 12. That gap is within normal luck.

## Where the data comes from

| Source | What it supplies | How it's used |
|---|---|---|
| Starter file (`data/saturday_lotto_history.csv`) | 2,053 draws, 1986 to 2025 | Loaded on first run |
| [au.lottonumbers.com](https://au.lottonumbers.com/saturday-lotto/results) | Every draw from 1986 onward, including the supplementary numbers and draw numbers | Read automatically: once in full on first run, then only for new draws |
| [thelott.com](https://www.thelott.com/saturday-lotto/results) | The official results | Checked by hand. Its results load in the browser and block automated access, so the app links to it |
| CSV import / manual entry | Any draw you add yourself | Fallbacks on the History page |

The app fetches results politely:
- It checks each site's robots.txt and stops if a page is disallowed.
- It identifies itself honestly.
- It makes at most one request every 2 seconds.
- It caches pages, and it never re-downloads a draw it already has.

Every draw is checked before it's stored: 6 different numbers from 1 to 45, 2 supplementary numbers
that differ from them, and a valid draw date. If two sources disagree about a draw, the app flags it
for you to review. It never silently picks one.

When the full history was first loaded, all 2,053 draws in the starter file matched
au.lottonumbers.com exactly.

## How to access it

### On your iPhone (no Mac needed)

Open **<https://bunzoi01.github.io/lottolens/>** in Safari, tap **Share**, then
**Add to Home Screen**. LottoLens then opens full-screen from its own icon. It works on Wi-Fi or
mobile data, and it shows the last copy it loaded when there's no signal.

This phone version is read-only: This Week, Analysis, History and Backtest. It's rebuilt every
Sunday morning by GitHub Actions, on GitHub's servers, so your Mac can be off. The page is public
to anyone who has the link, but it asks search engines not to list it.

### On your Mac (the full app)

1. **Install once.** You need a Mac with [uv](https://docs.astral.sh/uv/) or Python 3.12. Then
   download the project:

   ```sh
   git clone https://github.com/bunzoi01/lottolens.git
   cd lottolens
   ```

2. **Start it:**

   ```sh
   ./run.sh
   ```

   This sets everything up the first time, starts the app and opens your browser.

3. **Open it** at **<http://127.0.0.1:8765>**. The address only works on the same Mac, by design.
   The app has five pages:

   | Page | What's there |
   |---|---|
   | This Week | the next draw date, the 10 suggested games (copy or export as CSV), and last draw's result compared with the suggestions |
   | Analysis | charts and the fairness test, for the last 1, 2, 5 or 10 years, or all draws |
   | History | every draw, searchable; also "Fetch latest", CSV import and manual entry |
   | Backtest | LottoLens compared with random picks, as a chart and a table |
   | Settings | analysis window, factor weights, filters and data sources |

4. **Optional: weekly refresh in the background.**

   ```sh
   ./install_schedule.sh     # remove later with ./uninstall_schedule.sh
   ```

   This checks for the new result on Sunday morning (Sydney time), retries on Monday, and shows a
   notification when new suggestions are ready.

To stop the app, press `Ctrl+C` in the Terminal window where it's running. Your data stays in
`~/Library/Application Support/LottoLens/`, and logs are in `~/Library/Logs/LottoLens/`.
