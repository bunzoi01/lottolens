"""Parser and provider for au.lottonumbers.com Saturday Lotto pages."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..data.dates import now_sydney
from ..data.validate import Draw, DrawValidationError, make_draw
from .base import ResultsProvider
from .http import PoliteClient

log = logging.getLogger("lottolens.fetch.lottonumbers")

BASE = "https://au.lottonumbers.com"
SOURCE = "lottonumbers"

_LABEL = re.compile(r"Draw\s+([\d,]+)\s+(?:\w+day)\s+(\d{1,2}\s+\w+\s+\d{4})")


class ParseError(ValueError):
    pass


def parse_results_html(html: str, source: str = SOURCE) -> list[Draw]:
    """Extract draws from an archive or latest-results page.

    Both layouts wrap a "Draw 4,719 / Saturday 10 October 2026" label and a
    `div.balls-fx` block (6 winning balls + 2 `supplementary` balls) in one
    container (a `tr` on archive pages, a `div.resultBox` on the front page).
    """
    soup = BeautifulSoup(html, "html.parser")
    draws: dict[date, Draw] = {}
    skipped = 0
    for block in soup.select("div.balls-fx"):
        # Climb to the smallest ancestor holding the label, but never one that
        # also contains another draw's balls (that would mislabel the draw).
        label, node = None, block.parent
        while node is not None and len(node.select("div.balls-fx")) == 1:
            label = _LABEL.search(node.get_text(" ", strip=True))
            if label:
                break
            node = node.parent
        if label is None:
            skipped += 1
            continue
        winners, supps = [], []
        for li in block.select("li.ball"):
            text = li.get_text(strip=True)
            if not text.isdigit():
                continue
            (supps if "supplementary" in (li.get("class") or []) else winners).append(int(text))
        try:
            d = datetime.strptime(" ".join(label.group(2).split()), "%d %B %Y").date()
            draw = make_draw(
                d, winners, supps or None, draw_number=int(label.group(1).replace(",", "")), source=source
            )
        except (ValueError, DrawValidationError) as exc:
            log.warning("skipping unparseable draw block: %s", exc)
            skipped += 1
            continue
        draws.setdefault(draw.draw_date, draw)
    if not draws and (skipped or "balls" in html):
        raise ParseError("page layout not recognised: no draws could be parsed")
    return sorted(draws.values(), key=lambda d: d.draw_date)


class LottoNumbersProvider(ResultsProvider):
    name = SOURCE
    verify_url = f"{BASE}/saturday-lotto/results"

    def __init__(self, client: PoliteClient):
        self.client = client

    def fetch_latest(self) -> list[Draw]:
        return parse_results_html(self.client.get_text(f"{BASE}/saturday-lotto/results", ttl=1800))

    def fetch_year(self, year: int) -> list[Draw]:
        # Past years never change, so cache those pages forever.
        ttl = None if year < now_sydney().year else 1800
        html = self.client.get_text(f"{BASE}/saturday-lotto/results/{year}-archive", ttl=ttl)
        return [d for d in parse_results_html(html) if d.draw_date.year == year]
