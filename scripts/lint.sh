#!/usr/bin/env bash
# The same checks the CI `quality` job runs. Not part of the clone-and-run path:
# a reviewer only needs `docker compose up`.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff format --check
uv run ruff check
uv run mypy
uv run lint-imports
