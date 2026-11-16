#!/usr/bin/env bash
# Run CyberSyn from the source tree (development convenience).
# For the supported, containerised flow use: docker compose up --build
set -e

cd "$(dirname "$0")/src"

# Use the project virtual environment when setup.sh has created one.
if [ -x "../.venv/bin/python" ]; then
    PY="../.venv/bin/python"
else
    PY="python3"
fi

CYBERSYN_HOST="${CYBERSYN_HOST:-127.0.0.1}" \
CYBERSYN_PORT="${CYBERSYN_PORT:-5000}" \
exec "$PY" app.py "$@"
