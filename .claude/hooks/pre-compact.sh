#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OG_BIN="${SCRIPT_DIR}/.venv/bin/og"
[ -x "$OG_BIN" ] || OG_BIN="og"
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] && "$OG_BIN" extract --file "$TRANSCRIPT" --session-id "$SESSION_ID" >/dev/null 2>&1 || true
exit 0
