#!/usr/bin/env bash
#
# Install everything CyberSyn needs and create its virtual environment.
#
#   ./setup.sh          then  ./run.sh
#
# Works on Linux (Debian/Ubuntu, Fedora, Arch, Alpine) and on macOS. Windows
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
#
# Prefer 3.10–3.12: the photo-scan stack (facenet pins numpy<2, and numpy 1.x
# ships wheels up to cp312) has no wheels for 3.13+. A newer interpreter
# still runs the app — the photo route answers 503 — but say so loudly here,
# not from a traceback at first upload.
# ---------------------------------------------------------------------------

say "==> 1. Looking for Python 3..."

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.13 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        # `python` is Python 2 on older systems; skip it unless it is 3.x.
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' \
           >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    fi
done

[ -n "$PYTHON" ] || die "no Python 3 found on PATH.
   Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip
   Fedora:         sudo dnf install python3 python3-pip
   Arch:           sudo pacman -S python python-pip
   Alpine:         apk add python3 py3-pip py3-virtualenv
   macOS:          xcode-select --install   (or: brew install python3)"

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
   >/dev/null 2>&1; then
    die "Python 3.10 or newer is required, but $PYTHON is $("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])').
   Install a newer Python 3 and run this script again."
fi

PY_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PHOTO_OK=1
if "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)'; then
    PHOTO_OK=0
    say "    ⚠ $PYTHON is Python $PY_VERSION — too new for the photo-scan stack"
    say "      (numpy<2 / facenet-pytorch have no wheels for 3.13+)."
    say "      Chat will work, but /photo-scan will stay off."
    say "      To get photo scanning, install Python 3.12 and rerun setup:"
    say "        Debian/Ubuntu: sudo apt install python3.12 python3.12-venv"
    say "        Fedora:        sudo dnf install python3.12"
    say "        macOS:         brew install python@3.12"
    say "      then: rm -rf .venv && ./setup.sh"
fi

say "    using $PYTHON ($("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"

# ---------------------------------------------------------------------------
# 2. The virtual environment.
#
# An existing .venv is reused — unless it was built with a Python too new
# for the photo-scan stack while a compatible interpreter is available: then
# reusing it would silently keep /photo-scan off, so it is rebuilt.
# ---------------------------------------------------------------------------

if [ -d .venv ] && [ -x .venv/bin/python ]; then
    VENV_VER="$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ "$PHOTO_OK" = "1" ] && .venv/bin/python -c \
       'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)'; then
        say "==> 2. The existing .venv is Python $VENV_VER — too new for the"
        say "       photo-scan stack. Rebuilding it with $PYTHON..."
        rm -rf .venv
        "$PYTHON" -m venv .venv || die "could not recreate the virtual environment."
    else
        say "==> 2. Reusing the existing virtual environment (.venv, Python $VENV_VER)."
    fi
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

# ---------------------------------------------------------------------------
# 3. Dependencies.
# ---------------------------------------------------------------------------

say "==> 3. Upgrading pip..."
"$VENV_PY" -m pip install --upgrade pip || die "pip could not be upgraded."

say "==> 4. Installing dependencies from requirements.txt..."
say "    (torch is large; this is the slow step.)"
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
# 5. Verify. A dependency that installed but cannot be imported (a wheel for
#    the wrong platform, a missing system library) must be caught here —
#    not from a ModuleNotFoundError the next time ./run.sh starts.
# ---------------------------------------------------------------------------

say "==> 5. Verifying the installation..."
PROBE_MODULES="flask litellm cryptography"
if [ "$PHOTO_OK" = "1" ]; then
    PROBE_MODULES="$PROBE_MODULES numpy PIL cv2 facenet_pytorch rapidocr_onnxruntime easyocr"
fi
# Real imports, not find_spec: a wheel whose native libraries are missing
# (the classic libGL-less cv2) exists on disk yet fails at import time.
if ! MISSING="$("$VENV_PY" - "$PROBE_MODULES" <<'PY'
import importlib, sys
broken = []
for m in sys.argv[1].split():
    try:
        importlib.import_module(m)
    except Exception as exc:
        broken.append(f"{m} ({type(exc).__name__})")
print(" ".join(broken))
PY
)"; then
    die "the dependency probe itself failed to run — the virtual environment looks broken."
fi
if [ -n "$MISSING" ]; then
    die "these modules failed to import after install: $MISSING
   Scroll up for the pip error, fix it, and run ./setup.sh again."
fi
say "    all required modules import."

# ---------------------------------------------------------------------------
# 6. The model. Wanted, not required: without it the app still runs and
#    fetches the weights on first use, so a network failure here must not
#    undo the install that just succeeded.
# ---------------------------------------------------------------------------

say "==> 6. Pre-downloading the zero-shot model..."
if "$VENV_PY" -c "from transformers import pipeline; pipeline('zero-shot-classification', model='valhalla/distilbart-mnli-12-1')" \
   >/dev/null 2>&1; then
    say "    model ready."
else
    say "    skipped (no network, or transformers is not installed yet)."
    say "    The app will fetch it the first time a prompt is screened."
fi

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
