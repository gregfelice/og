#!/usr/bin/env bash
set -euo pipefail
OG_BIN="/home/gregf/development/og/.venv/bin/og"
[ -x "$OG_BIN" ] || OG_BIN="og"
notify-send -i dialog-information -t 3000 "🟢 OG" "Injecting context" 2>/dev/null &
exec "$OG_BIN" inject 2>/dev/null
