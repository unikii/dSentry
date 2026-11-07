#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

venv_is_broken() {
    # Missing interpreter or entry point.
    [ ! -x "$VENV/bin/python" ] && return 0
    [ ! -f "$VENV/bin/uvicorn" ] && return 0
    # Stale venv after the project directory was renamed/moved:
    # script shebangs still point at the old absolute path.
    local interp
    interp="$(sed -n '1s/^#!//p' "$VENV/bin/uvicorn" | awk '{print $1}')"
    if [ -n "$interp" ] && [ ! -x "$interp" ]; then
        return 0
    fi
    # Dependencies gone (e.g. partial install).
    if ! "$VENV/bin/python" -c "import uvicorn" 2>/dev/null; then
        return 0
    fi
    return 1
}

if [ ! -d "$VENV" ] || venv_is_broken; then
    rm -rf "$VENV"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

cd "$SCRIPT_DIR"
# Dev-only launcher: bind loopback by default. Set HOST=0.0.0.0 to expose the
# API on the LAN; the API port has no TLS and should normally sit behind a proxy.
exec "$VENV/bin/uvicorn" app.main:app --host "${HOST:-127.0.0.1}" --port 9090 --reload
