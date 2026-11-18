#!/usr/bin/env bash
#
# Run CyberSyn from the source tree.
#
#   ./run.sh                        start the server
#   ./run.sh seed <user> [password] create an administrator, then exit
#   CYBERSYN_HOST=0.0.0.0 ./run.sh  let other machines reach it
#
# Host, port and every path come from includes/constants.json, so editing
# that file is enough — and the environment still wins where it should,
# because a container has to bind 0.0.0.0 without editing a tracked file.
#
# For the containerised flow instead:  docker compose up --build

# Started as `sh run.sh`? On Debian and friends that is dash, which has no
# [[ ]] and no arrays. Hand over to bash rather than fail on line 40.
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    fi
    echo "run.sh needs bash. Install it, or start it with: bash run.sh" >&2
    exit 1
fi

set -e

# Sourcing would let the `exec` at the end replace the caller's shell.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    echo "run.sh must be executed, not sourced. Use: ./run.sh" >&2
    return 1 2>/dev/null || exit 1
fi

# Resolve this script's own directory, following symlinks. `readlink -f` is
# a GNU extension and macOS does not have it, so walk the links by hand;
# plain `readlink` (no -f) does exist everywhere we support.
script_dir() {
    local source="$1" target dir
    while [ -L "$source" ] && command -v readlink >/dev/null 2>&1; do
        target="$(readlink "$source")" || break
        case "$target" in
            /*) source="$target" ;;
            *)  source="$(dirname "$source")/$target" ;;
        esac
    done
    dir="$(cd "$(dirname "$source")" >/dev/null 2>&1 && pwd -P)"
    [ -n "$dir" ] || dir="$(cd "$(dirname "$1")" >/dev/null 2>&1 && pwd)"
    printf '%s\n' "$dir"
}

ROOT="$(script_dir "${BASH_SOURCE[0]}")"

say() { printf '%s\n' "$*"; }
die() { printf 'run.sh: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Which Python. The virtual environment setup.sh built is the only one that
# has the dependencies, so it comes first.
# ---------------------------------------------------------------------------

. "$ROOT/tools/local_python.sh"

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    # Created by setup.sh running under Git Bash or Cygwin on Windows.
    die "this looks like a Windows virtual environment (.venv/Scripts).
   The scanners and the server are not supported on Windows.
   Use WSL (Ubuntu on Windows) and run setup.sh again inside it,
   or use Docker:  docker compose up --build"
fi

if has_project_venv; then
    PY=$(venv_python)
else
    # Keep supporting manually installed dependencies, including a versioned
    # interpreter on PATH behind an incompatible system python3.
    PY=$(path_python) || die "no Python 3.11–3.13 environment found. Run ./setup.sh first.
   Setup can provision Python 3.12 with uv. On Arch, if uv is missing: sudo pacman -S --needed uv"
    say "==> No project .venv found. Using Python from PATH; run ./setup.sh if dependencies are missing."
fi
say "==> Using $("$PY" --version) at $PY"

# ---------------------------------------------------------------------------
# Host and port: constants.json, with the environment taking precedence.
# ---------------------------------------------------------------------------

read_constants() {
    "$PY" - "$ROOT/includes/constants.json" <<'PYTHON'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        constants = json.load(fh)
    print(constants.get("HOST", "127.0.0.1"), int(constants.get("PORT", 5000)))
except Exception:
    # A malformed or missing constants file must not stop the server: the
    # defaults below are the same ones config.py falls back to.
    print("127.0.0.1", 5000)
PYTHON
}

DEFAULTS="$(read_constants)"
DEFAULT_HOST="${DEFAULTS%% *}"
DEFAULT_PORT="${DEFAULTS##* }"

CYBERSYN_HOST="${CYBERSYN_HOST:-$DEFAULT_HOST}"
CYBERSYN_PORT="${CYBERSYN_PORT:-$DEFAULT_PORT}"
export CYBERSYN_HOST CYBERSYN_PORT

# 0.0.0.0 means "every interface"; it is not something to type into a browser.
case "$CYBERSYN_HOST" in
    0.0.0.0|"::") SHOWN_HOST="127.0.0.1" ;;
    *)            SHOWN_HOST="$CYBERSYN_HOST" ;;
esac

say "==> CyberSyn will listen on $CYBERSYN_HOST:$CYBERSYN_PORT"
say "==> Open http://$SHOWN_HOST:$CYBERSYN_PORT/"
say ""

# app.py expects to be started from src/, which is also what puts its own
# directory on sys.path so `import config` works.
cd "$ROOT/src"
exec "$PY" app.py "$@"
