#!/usr/bin/env bash
# Runs the suite with coverage.
#
# Integration tests need a real MongoDB, so this brings up just that service
# from docker-compose.yml and leaves the rest alone. If MongoDB was already
# running (a `docker compose up` session is open), it is left running on exit —
# only a container this script started gets stopped.
#
# Tests marked `live` are excluded: they hit the real model provider. Run them
# on purpose with `uv run pytest -m live`.
set -euo pipefail
cd "$(dirname "$0")/.."

compose() { docker compose "$@"; }

already_running=0
if [ "$(compose ps --status running --services 2>/dev/null | grep -c '^mongo$')" -gt 0 ]; then
  already_running=1
fi

compose up -d --wait mongo

cleanup() {
  if [ "$already_running" -eq 0 ]; then
    compose stop mongo
  fi
}
trap cleanup EXIT

uv run pytest -m "not live" "$@"
