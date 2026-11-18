#!/usr/bin/env bash
#
# Install everything CyberSyn needs and create its virtual environment.
#
#   ./setup.sh          then  ./run.sh
#
# Works on glibc Linux and on Apple Silicon macOS. Windows
# is not supported: use WSL, or Docker (docker compose up --build).
#
# Safe to run twice: an existing .venv is reused, not destroyed.

# `sh setup.sh` runs dash on Debian. Hand over to bash first.
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    fi
    echo "setup.sh needs bash. Install it, or start it with: bash setup.sh" >&2
    exit 1
fi

set -e

if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    echo "setup.sh must be executed, not sourced. Use: ./setup.sh" >&2
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
cd "$ROOT"

say() { printf '%s\n' "$*"; }
die() {
    printf '\nsetup failed: %s\n' "$*" >&2
    exit 1
}

case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*)
        die "Windows is not supported.
   The scanners need torch and spaCy, which do not build reliably here.
   Use WSL (wsl --install, then run this script inside Ubuntu),
   or use Docker:  docker compose up --build" ;;
esac

# ---------------------------------------------------------------------------
# 1–2. Use a compatible project environment, or provision one alongside the
# system Python. In particular, Arch's current `python` may be too new.
# ---------------------------------------------------------------------------

. "$ROOT/tools/local_python.sh"

say "==> 1. Looking for Python 3.11–3.13..."
if has_project_venv; then
    say "==> 2. Checking the existing virtual environment (.venv)."
elif PYTHON=$(path_python); then
    say "==> 2. Creating .venv with $PYTHON..."
    "$PYTHON" -m venv .venv || die "could not create .venv with $PYTHON.
   On Debian/Ubuntu install the matching python3-venv package, then rerun ./setup.sh."
elif command -v uv >/dev/null 2>&1; then
    say "==> 2. Using uv to create .venv with Python 3.12 (downloaded if needed)..."
    uv venv --python 3.12 --seed .venv || die "uv could not provision Python 3.12 and pip.
   Check the download error above, or put Python 3.11–3.13 on PATH and rerun ./setup.sh."
else
    die "the pinned dependencies need Python 3.11–3.13. No compatible interpreter was found.
   Install uv (on Arch: sudo pacman -S --needed uv) and rerun ./setup.sh,
   or put a supported Python on PATH. Do not downgrade your system Python."
fi
VENV_PY=$(venv_python)
say "    using $("$VENV_PY" --version) at $VENV_PY"

# ---------------------------------------------------------------------------
# 3. Dependencies.
# ---------------------------------------------------------------------------

say "==> 3. Upgrading pip..."
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    "$VENV_PY" -m ensurepip --upgrade || die "the project .venv has no pip. Install venv/ensurepip for its interpreter and rerun ./setup.sh."
fi
"$VENV_PY" -m pip install --upgrade pip || die "pip could not be upgraded."

say "==> 4. Installing dependencies from requirements.txt..."
say "    (torch is large; this is the slow step.)"
if [ "$(uname -s)" = Linux ]; then
    # pip can otherwise keep an already-installed CUDA wheel at the same pin.
    if "$VENV_PY" -c 'import torch, sys; sys.exit(torch.version.cuda is None)' 2>/dev/null; then
        "$VENV_PY" -m pip uninstall -y torch
    fi
    "$VENV_PY" -m pip install --index-url https://download.pytorch.org/whl/cpu "$(grep '^torch==' requirements.txt)" \
        || die "could not install the CPU build of PyTorch"
fi
if ! "$VENV_PY" -m pip install -r requirements.txt; then
    cat >&2 <<'HINT'

pip could not install every dependency.

  * No network, or a proxy:  pip needs to reach pypi.org and
    download.pytorch.org. Check the connection and run ./setup.sh again.
  * Alpine/musl: torch ships no musl wheels. Use Debian, Fedora, Arch,
    macOS, or Docker.
  * Old CPU: torch needs x86-64-v2 (2011 or later) or arm64.
HINT
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Verify imports, model weights and CPU inference together. A dependency
#    resolver or a downloaded config alone cannot tell if the models work.
# ---------------------------------------------------------------------------

"$VENV_PY" -m pip check || die "incompatible packages in the virtual environment"
say "==> 5. Loading the local models and verifying CPU inference..."
"$VENV_PY" src/MLscripts/model_cache.py || die "model verification failed; check the weights, dependencies and network, then rerun ./setup.sh"

# ---------------------------------------------------------------------------
# Where to go next.
# ---------------------------------------------------------------------------

cat <<'NEXT'

==> Setup complete.

    ./run.sh

NEXT

# Offer an activated shell, but only where we know how. `exec "$SHELL"
# --rcfile` is bash-specific and zsh -- macOS's default shell -- does not
# accept it, which used to strand the user in a shell that never printed a
# prompt. Printing the command is portable and never wrong.
case "${SHELL##*/}" in
    bash|zsh|ksh)
        say "To activate the virtual environment in this shell:"
        say "    source .venv/bin/activate"
        ;;
    fish)
        say "To activate the virtual environment in this shell:"
        say "    source .venv/bin/activate.fish"
        ;;
    csh|tcsh)
        say "To activate the virtual environment in this shell:"
        say "    source .venv/bin/activate.csh"
        ;;
esac
