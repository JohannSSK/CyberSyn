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
# [[ ]] and no arrays. Hand over to bash before using either.
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    fi
    echo "run.sh needs bash. Install it, or start it with: bash run.sh" >&2
    exit 1
fi

# Sourcing would let the `exec` at the end replace the caller's shell.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    echo "run.sh must be executed, not sourced. Use: ./run.sh" >&2
    return 1
fi

set -e

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
not_ready() {
    {
        printf '\nCyberSyn cannot start: the local screeners are not ready.\n'
        printf '%s\n' "$1"
        printf 'Run ./setup.sh (or cybersyn --setup) to repair the installation.\n'
        printf 'For debugging only, CYBERSYN_SKIP_VERIFY=1 skips the dependency probe.\n'
    } >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Which Python. The virtual environment setup.sh built is the only one that
# has the dependencies, so it comes first.
# ---------------------------------------------------------------------------

# shellcheck source=tools/local_python.sh disable=SC1091
. "$ROOT/tools/local_python.sh"

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    # Created by setup.sh running under Git Bash or Cygwin on Windows.
    not_ready "This looks like a Windows virtual environment (.venv/Scripts).
Use WSL (Ubuntu on Windows) or Docker: docker compose up --build"
fi

skip_verify=${CYBERSYN_SKIP_VERIFY:-0}
if has_project_venv; then
    PY=$(venv_python 2>&1) || not_ready "$PY"
elif [ "$skip_verify" = 1 ]; then
    PY=$(path_python) || not_ready "No Python 3.11–3.13 interpreter found on PATH."
    say "==> CYBERSYN_SKIP_VERIFY=1: no project .venv found; using Python from PATH."
else
    not_ready "No project .venv found."
fi
say "==> Using $("$PY" --version) at $PY"

# Seeding does not screen prompts. All normal server starts must pass both
# checks before binding, without fetching packages or weights.
if [ "${1:-}" != seed ] && [ "$skip_verify" != 1 ]; then
    cd "$ROOT"
    say "==> Checking installed dependencies and cached scanner models..."
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$PY" -m pip check || not_ready "pip check failed."
    "$PY" src/MLscripts/model_cache.py --verify || not_ready "Offline model verification failed."
fi

# Use config.py as the source of truth for the bind and paths. The server
# prints the actual URL after binding. exec keeps Ctrl-C and SIGTERM on the
# server process, and unbuffered output also works when launched from a service.
cd "$ROOT/src"
exec "$PY" -u app.py "$@"
