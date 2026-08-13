#!/usr/bin/env bash
# Every check CI runs, in the order it runs them.
#
# It used to cover only the `quality` job, so a bandit finding could pass here
# and fail on push — which it did. If a check gates the build, it belongs in the
# one command a developer runs before pushing.
#
# Not part of the clone-and-run path: a reviewer only needs `docker compose up`.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ format"
uv run ruff format --check
echo "→ lint"
uv run ruff check
echo "→ types"
uv run mypy
echo "→ architecture"
uv run lint-imports
echo "→ security"
uv run bandit -r app -q
echo "→ dependencies"
uv run pip-audit

echo
echo "All CI checks passed."
