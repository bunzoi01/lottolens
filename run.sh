#!/usr/bin/env bash
# Start LottoLens: create the environment if needed, start the server, open the browser.
set -euo pipefail
cd "$(dirname "$0")"

# Keep the virtualenv out of this (OneDrive-synced) folder.
export UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/LottoLens/venv"
unset VIRTUAL_ENV

if command -v uv >/dev/null 2>&1; then
  uv sync --python 3.12 --quiet
  PY="$UV_PROJECT_ENVIRONMENT/bin/python"
else
  echo "uv not found; using venv + pip"
  PY_BIN="$(command -v python3.12 || true)"
  [ -n "$PY_BIN" ] || { echo "Python 3.12 is required (brew install python@3.12, or install uv)"; exit 1; }
  if [ ! -x "$UV_PROJECT_ENVIRONMENT/bin/python" ]; then
    "$PY_BIN" -m venv "$UV_PROJECT_ENVIRONMENT"
  fi
  "$UV_PROJECT_ENVIRONMENT/bin/pip" install --quiet -e . pytest
  PY="$UV_PROJECT_ENVIRONMENT/bin/python"
fi

exec "$PY" -m lottolens serve --open "$@"
