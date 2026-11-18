# shellcheck shell=bash
# setup.sh prepends the shebang and DEFAULT_CYBERSYN_HOME to this launcher.
set -e

usage() {
    cat <<'USAGE'
Usage: cybersyn [-p PORT | --port PORT | --port=PORT] [--host HOST] [--setup] [--] [app args...]
       cybersyn seed <user> [password]
       cybersyn -h | --help

--setup  Repair local dependencies, then start CyberSyn.
USAGE
}

usage_error() {
    printf 'cybersyn: %s\n' "$1" >&2
    usage >&2
    exit 2
}

set_port() {
    local port="$1" error='port must be an integer from 0 to 65535.'
    [[ -n "$port" && "$port" != *[!0123456789]* ]] || usage_error "$error"
    # Strip leading zeros (Bash reads them as octal), and reject numbers
    # too large for the range before doing arithmetic that could overflow.
    port=${port#"${port%%[!0]*}"}
    port=${port:-0}
    if [[ ${#port} -gt 5 ]] || (( port > 65535 )); then
        usage_error "$error"
    fi
    export CYBERSYN_PORT="$port"
}

repair=0
args=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -p|--port)
            [ "$#" -ge 2 ] || usage_error "$1 requires a port."
            set_port "$2"
            shift 2 ;;
        --port=*) set_port "${1#*=}"; shift ;;
        --host)
            [[ "$#" -ge 2 && -n "$2" && "$2" != -* ]] || usage_error '--host requires a host.'
            export CYBERSYN_HOST="$2"
            shift 2 ;;
        --setup) repair=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; args+=("$@"); break ;;
        seed) args+=("$@"); break ;;  # Credentials can look like options.
        *) args+=("$1"); shift ;;
    esac
done

root=${CYBERSYN_HOME:-${DEFAULT_CYBERSYN_HOME:-}}
if [[ -z "$root" || ! -f "$root/run.sh" || ! -x "$root/run.sh" ]]; then
    printf 'cybersyn: CyberSyn checkout not found at "%s".\n' "$root" >&2
    printf 'Set CYBERSYN_HOME to its location or rerun ./setup.sh from the checkout.\n' >&2
    exit 1
fi

if [ "$repair" = 1 ]; then
    "$root/setup.sh"
fi
exec "$root/run.sh" "${args[@]}"
