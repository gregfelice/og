#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OG_BIN="${SCRIPT_DIR}/.venv/bin/og"
[ -x "$OG_BIN" ] || OG_BIN="og"
notify-send -i dialog-information -t 3000 "🟢 OG" "Injecting context" 2>/dev/null &
exec "$OG_BIN" inject 2>/dev/null
