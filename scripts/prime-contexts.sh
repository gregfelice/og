#!/usr/bin/env bash
# Prime the OG knowledge store from all Claude Code transcripts.
# Processes ~/development and ~/operations project sessions.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OG_BIN="${SCRIPT_DIR}/.venv/bin/og"
MIN_SIZE_KB=5
MAX_PARALLEL=4

if [ ! -x "$OG_BIN" ]; then
    echo "ERROR: og binary not found at $OG_BIN" >&2
    exit 1
fi

total=0
success=0
skipped=0
failed=0

process_file() {
    local file="$1"
    local project_id="$2"
    local session_id
    session_id=$(basename "$file" .jsonl)

    "$OG_BIN" extract --file "$file" --session-id "$session_id" --project "$project_id" 2>/dev/null
}

# Collect all work items
declare -a files=()
declare -a projects=()

while IFS= read -r file; do
    # Skip small files
    size_kb=$(du -k "$file" | cut -f1)
    if [ "$size_kb" -lt "$MIN_SIZE_KB" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    # Derive project_id from directory name
    dir=$(dirname "$file")
    project_id=$(basename "$dir" | sed 's/^-home-gregf-//')

    files+=("$file")
    projects+=("$project_id")
    total=$((total + 1))
done < <(find ~/.claude/projects/ -maxdepth 2 -name "*.jsonl" -type f \
    | grep -E "(-home-gregf-development-|-home-gregf-operations)" \
    | grep -v subagents \
    | sort)

echo "Priming OG knowledge store: $total transcripts to process ($skipped skipped < ${MIN_SIZE_KB}K)"
echo ""

# Process with bounded parallelism
running=0
completed=0
for i in "${!files[@]}"; do
    file="${files[$i]}"
    project_id="${projects[$i]}"
    session_id=$(basename "$file" .jsonl)

    (
        result=$(process_file "$file" "$project_id" 2>&1) || true
        echo "  [$project_id] $session_id — $result"
    ) &

    running=$((running + 1))

    if [ "$running" -ge "$MAX_PARALLEL" ]; then
        wait -n 2>/dev/null || true
        running=$((running - 1))
    fi
done

# Wait for remaining
wait

echo ""
echo "Done. Processed $total transcripts."
