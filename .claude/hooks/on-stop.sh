#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OG_BIN="${SCRIPT_DIR}/.venv/bin/og"
[ -x "$OG_BIN" ] || OG_BIN="og"
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    notify-send -i dialog-information -t 3000 "🟢 OG" "Extracting knowledge (on-stop)" 2>/dev/null &
    "$OG_BIN" extract --file "$TRANSCRIPT" --session-id "$SESSION_ID" >/dev/null 2>&1 || true
fi
exit 0
