"""ResultsProvider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..data.validate import Draw


class ResultsProvider(ABC):
    name: str = "provider"
    #: Page a person can open to check a draw by hand.
    verify_url: str = ""

    @abstractmethod
    def fetch_latest(self) -> list[Draw]:
        """The most recent draws the source shows on its front results page."""

    @abstractmethod
    def fetch_year(self, year: int) -> list[Draw]:
        """Every draw for a calendar year."""


# thelott.com renders results client-side and its JSON API is behind bot
# protection (HTTP 403 for non-browser clients), so it is a manual cross-check:
# the UI links here and flags any manual entry that conflicts with stored data.
THELOTT_VERIFY_URL = "https://www.thelott.com/saturday-lotto/results"
