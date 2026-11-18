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
# 1. A Python 3 interpreter, under one of the names it is shipped as.
# ---------------------------------------------------------------------------

say "==> 1. Looking for Python 3..."

PYTHON=""
for candidate in python3 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        # `python` is Python 2 on older systems; skip it unless it is 3.x.
        if "$candidate" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)' \
           >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    fi
done

[ -n "$PYTHON" ] || die "no supported Python (3.11–3.13) found on PATH.
   Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip
   Fedora:         sudo dnf install python3 python3-pip
   Arch:           sudo pacman -S python python-pip
   Alpine:         apk add python3 py3-pip py3-virtualenv
   macOS:          xcode-select --install   (or: brew install python3)"

if ! "$PYTHON" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)' \
   >/dev/null 2>&1; then
    die "Python 3.11–3.13 is required, but $PYTHON is $("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])').
   Install a newer Python 3 and run this script again."
fi

say "    using $PYTHON ($("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"

# ---------------------------------------------------------------------------
# 2. The virtual environment.
# ---------------------------------------------------------------------------

if [ -d .venv ] && [ -x .venv/bin/python ]; then
    say "==> 2. Reusing the existing virtual environment (.venv)."
else
    say "==> 2. Creating the virtual environment (.venv)..."
    if ! "$PYTHON" -m venv .venv 2>/tmp/cybersyn-venv-error; then
        cat /tmp/cybersyn-venv-error >&2 || true
        rm -f /tmp/cybersyn-venv-error
        # The usual cause, and it is not guessable from the traceback.
        die "could not create a virtual environment.
   Debian/Ubuntu almost always needs:  sudo apt install python3-venv
   Fedora:                             sudo dnf install python3-virtualenv
   Alpine:                             apk add py3-virtualenv
   then run ./setup.sh again."
    fi
    rm -f /tmp/cybersyn-venv-error
fi

VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || die "the virtual environment was created but has no interpreter at .venv/bin/python."
"$VENV_PY" -c 'import sys; sys.exit(not (3, 11) <= sys.version_info < (3, 14))' \
    || die "the existing .venv needs Python 3.11–3.13. Recreate it with the supported interpreter."

# ---------------------------------------------------------------------------
# 3. Dependencies.
# ---------------------------------------------------------------------------

say "==> 3. Upgrading pip..."
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
