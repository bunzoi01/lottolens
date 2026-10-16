"""macOS notifications via osascript."""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("lottolens.notify")


def _applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str) -> bool:
    if not shutil.which("osascript"):
        return False
    script = f"display notification {_applescript_string(message)} with title {_applescript_string(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10, capture_output=True)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("notification failed: %s", exc)
        return False
