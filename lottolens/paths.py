"""Filesystem locations and logging setup.

Everything lives under the standard macOS per-user folders. Set LOTTOLENS_HOME to
redirect data, cache and logs (the tests do this so they never touch real data).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_CSV = PROJECT_ROOT / "data" / "saturday_lotto_history.csv"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


def app_dir() -> Path:
    override = os.environ.get("LOTTOLENS_HOME")
    base = Path(override) if override else Path.home() / "Library" / "Application Support" / "LottoLens"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return app_dir() / "lotto.db"


def cache_dir() -> Path:
    path = app_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    override = os.environ.get("LOTTOLENS_HOME")
    path = Path(override) / "logs" if override else Path.home() / "Library" / "Logs" / "LottoLens"
    path.mkdir(parents=True, exist_ok=True)
    return path


_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Log to ~/Library/Logs/LottoLens/lottolens.log and stderr. Safe to call repeatedly."""
    global _configured
    if _configured:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger("lottolens")
    root.setLevel(level)
    file_handler = RotatingFileHandler(log_dir() / "lottolens.log", maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream)
    _configured = True
