#!/usr/bin/env bash
# Configure the model provider key and bring the stack up, in one pass.
#
# This is a convenience wrapper, not a requirement: `docker compose up` on its
# own does everything except ask for the key, and remains the guaranteed path.
# What this adds is not having to discover the key is missing, stop, set it, and
# start again.
#
#   ./scripts/start.sh                  prompts for the key (hidden input)
#   ./scripts/start.sh --key sk-or-...  non-interactive, for automation
#
# The prompt is the default on purpose: an argument is recorded in your shell
# history in plain text, and an API key does not belong there.
set -euo pipefail
cd "$(dirname "$0")/.."

KEY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY="${2:-}"; shift 2 ;;
    --key=*) KEY="${1#*=}"; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1. Try --help." >&2; exit 2 ;;
  esac
done

# --- prerequisites ----------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Get it at https://docs.docker.com/get-docker/" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is not available (an outdated Docker Desktop?)." >&2
  exit 1
fi

# --- .env -------------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

current_key="$(grep -E '^OPENROUTER_API_KEY=' .env | cut -d= -f2- || true)"

if [ -n "$current_key" ] && [ -z "$KEY" ]; then
  # Never overwrite a key the user already set without being told to.
  echo "An API key is already configured in .env. Leaving it alone."
elif [ -z "$KEY" ]; then
  echo
  echo "Paste your OpenRouter API key, or press Enter to skip."
  echo "Free key, no card required: https://openrouter.ai/keys"
  # -s so the key is not echoed to the terminal, and does not end up in a
  # screen recording or a scrollback buffer.
  read -r -s -p "  API key: " KEY || true
  echo
fi

if [ -n "$KEY" ]; then
  # A temp file plus mv, rather than sed -i: the key never sits in a shell
  # argument list where `ps` could read it, and a failure mid-write cannot
  # leave a truncated .env.
  tmp="$(mktemp)"
  KEY="$KEY" awk -F= '
    /^OPENROUTER_API_KEY=/ { print "OPENROUTER_API_KEY=" ENVIRON["KEY"]; found=1; next }
    { print }
    END { if (!found) print "OPENROUTER_API_KEY=" ENVIRON["KEY"] }
  ' .env > "$tmp"
  mv "$tmp" .env
  chmod 600 .env
  echo "API key written to .env."
else
  echo
  echo "No key configured. The app will start and everything except answering"
  echo "messages will work — it says so in the interface rather than failing."
fi

# --- up ---------------------------------------------------------------------
echo
echo "Starting (first run builds the images, which takes a minute)..."
docker compose up -d --build --wait

WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2- || true)"
cat <<EOF

Ready.

  App:      http://localhost:${WEB_PORT:-8080}
  API docs: http://localhost:8000/docs
  Logs:     docker compose logs -f api
  Stop:     docker compose down

EOF
