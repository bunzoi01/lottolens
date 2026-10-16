#!/usr/bin/env bash
# Run the test suite (offline; tests never touch the network or your real data).
set -euo pipefail
cd "$(dirname "$0")"
export UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/LottoLens/venv"
unset VIRTUAL_ENV
uv sync --python 3.12 --quiet
exec uv run pytest -q "$@"
