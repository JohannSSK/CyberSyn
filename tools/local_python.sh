# shellcheck shell=bash
# Shared by setup.sh and run.sh after they resolve ROOT and define die().

# Print the first interpreter that can run the pinned stack. For a project
# venv, also check where pip would install: a dangling/replaced Python after
# a system upgrade must never turn a local install into a system install.
find_python() {
    local prefix="$1" candidate
    shift
    for candidate in "$@"; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c '
import os, sys
if not (3, 11) <= sys.version_info < (3, 14):
    sys.exit(1)
if sys.argv[1] and (sys.prefix == sys.base_prefix or not os.path.samefile(sys.prefix, sys.argv[1])):
    sys.exit(1)
print(sys.executable)' "$prefix" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

has_project_venv() {
    [ -e "$ROOT/.venv" ] || [ -L "$ROOT/.venv" ]
}

venv_python() {
    find_python "$ROOT/.venv" "$ROOT/.venv/bin/python" "$ROOT/.venv/bin/python3" ||
        die "the existing .venv is broken or does not use Python 3.11–3.13. Move it aside and rerun ./setup.sh."
}

path_python() {
    find_python '' python3 python3.13 python3.12 python3.11 python
}
