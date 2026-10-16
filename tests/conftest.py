import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point all app data/logs at a temp dir so tests never touch real data."""
    monkeypatch.setenv("LOTTOLENS_HOME", str(tmp_path / "home"))
    yield tmp_path / "home"


@pytest.fixture
def db(tmp_path):
    from lottolens.data.db import Database

    return Database(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test tries a real HTTP request."""
    import httpx

    def blocked(*args, **kwargs):
        raise RuntimeError("tests must not hit the network")

    # Only the real transport is blocked; httpx.MockTransport stays usable.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
