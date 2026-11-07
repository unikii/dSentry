#!/bin/sh
# Thin wrapper so user management feels like bash:
#   ./scripts/users.sh list
#   ./scripts/users.sh create alice          # prompts for password securely
#   ./scripts/users.sh set-password alice    # resets password, revokes sessions
#
# The wrapper uses docker-compose.yml by default. Override it with
# -f/--compose-file <file> or COMPOSE_FILE when using another Compose file.
#   ./scripts/users.sh -f docker-compose.yml list
#   COMPOSE_FILE=docker-compose.yml ./scripts/users.sh list
#
# Commands missing a required username prompt for it when interactive.
#
# Runs manage_users.py inside the API container when it's up,
# otherwise falls back to the local venv (hub/api/.venv).
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

usage() {
    echo "Usage: $(basename "$0") [-f|--compose-file <file>] <command> [args]" >&2
    echo "" >&2
    echo "Commands:" >&2
    echo "  list                                   List users" >&2
    echo "  create <username> [--password PW|--no-password]   (private mode only)" >&2
    echo "  set-password <username> [--password PW] [--force] (private mode only)" >&2
    echo "  clear-password <username>                         (private mode only)" >&2
    echo "  enable|disable <username>" >&2
    echo "" >&2
    echo "Compose file: -f <file> or COMPOSE_FILE (default: docker-compose.yml)" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  ./scripts/users.sh list" >&2
    echo "  ./scripts/users.sh create alice" >&2
    echo "  ./scripts/users.sh -f docker-compose.yml list" >&2
}

# Extract our own -f/--compose-file flag; the rest goes to manage_users.py.
PASSTHROUGH=""
SHOW_HELP=0
while [ $# -gt 0 ]; do
    case "$1" in
        -f|--compose-file)
            [ $# -lt 2 ] && { echo "Missing value for $1" >&2; exit 1; }
            COMPOSE_FILE="$2"
            shift 2
            ;;
        --compose-file=*)
            COMPOSE_FILE="${1#--compose-file=}"
            shift
            ;;
        -h|--help)
            SHOW_HELP=1
            PASSTHROUGH="$PASSTHROUGH $1"
            shift
            break
            ;;
        *)
            PASSTHROUGH="$PASSTHROUGH $1"
            shift
            ;;
    esac
done
# Word-splitting of $PASSTHROUGH is intentional (POSIX sh, no arrays).
# shellcheck disable=SC2086

# No command at all: friendly usage, no docker calls.
# shellcheck disable=SC2086
set -- $PASSTHROUGH
if [ $# -eq 0 ]; then
    usage
    exit 2
fi

stack_up() {
    # True when the API container of the selected Compose file is running.
    docker compose -f "$ROOT/$COMPOSE_FILE" ps api 2>/dev/null | grep -q -E "Up|running"
}

if [ "$SHOW_HELP" -eq 1 ]; then
    # Help needs no stack: prefer the local venv, else the running
    # container, else just our own usage.
    usage
    VENV_HELP="$ROOT/hub/api/.venv"
    if [ -x "$VENV_HELP/bin/python" ]; then
        cd "$ROOT/hub/api"
        # shellcheck disable=SC2086
        exec "$VENV_HELP/bin/python" manage_users.py $PASSTHROUGH
    fi
    if [ -f "$ROOT/$COMPOSE_FILE" ] && stack_up; then
        # shellcheck disable=SC2086
        exec docker compose -f "$ROOT/$COMPOSE_FILE" exec -T api python /hub/manage_users.py $PASSTHROUGH
    fi
    exit 0
fi

# Fill in a missing username interactively instead of dumping an
# argparse error.
CMD="$1"
case "$CMD" in
    create|set-password|clear-password|enable|disable)
        shift
        HAS_USER=0
        for a in "$@"; do
            case "$a" in
                -*) ;;
                *) HAS_USER=1; break ;;
            esac
        done
        if [ "$HAS_USER" -eq 0 ] && [ -t 0 ]; then
            printf "Username: " >&2
            read -r INPUT_USER
            if [ -z "$INPUT_USER" ]; then
                echo "username is required" >&2
                exit 2
            fi
            PASSTHROUGH="$PASSTHROUGH $INPUT_USER"
        fi
        ;;
esac

if [ ! -f "$ROOT/$COMPOSE_FILE" ]; then
    echo "Compose file not found: $ROOT/$COMPOSE_FILE" >&2
    exit 1
fi

if stack_up; then
    if [ -t 0 ]; then
        # Interactive terminal: let compose allocate a TTY so the secure
        # getpass() password prompt inside the container works.
        # shellcheck disable=SC2086
        exec docker compose -f "$ROOT/$COMPOSE_FILE" exec api python /hub/manage_users.py $PASSTHROUGH
    fi
    # Non-interactive (pipe/CI): no TTY to allocate; password must come
    # via --password (or --no-password in private mode).
    # shellcheck disable=SC2086
    exec docker compose -f "$ROOT/$COMPOSE_FILE" exec -T api python /hub/manage_users.py $PASSTHROUGH
fi

VENV="$ROOT/hub/api/.venv"
if [ -x "$VENV/bin/python" ]; then
    cd "$ROOT/hub/api"
    # shellcheck disable=SC2086
    exec "$VENV/bin/python" manage_users.py $PASSTHROUGH
fi

echo "API container is not running and no local venv found." >&2
echo "Start the stack first: docker compose up -d" >&2
exit 1
