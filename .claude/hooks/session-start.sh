#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OG_BIN="${SCRIPT_DIR}/.venv/bin/og"
[ -x "$OG_BIN" ] || OG_BIN="og"
exec "$OG_BIN" inject 2>/dev/null
