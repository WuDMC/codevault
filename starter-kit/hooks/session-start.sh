#!/bin/bash
# session-start.sh - Initialize session logging and inject context reminder
# Hook: SessionStart (sync) — output goes to Claude as context

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
mkdir -p "$LOG_DIR"

SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

# Write session header
echo "{\"event\":\"session_start\",\"timestamp\":\"$TIMESTAMP\",\"session_id\":\"$SESSION_ID\"}" >> "$SESSION_LOG"

# Cleanup logs older than 30 days
find "$LOG_DIR" -name "session-*.jsonl" -mtime +30 -delete 2>/dev/null

# Short reminder — full protocol is in .claude/skills/memory-agent/SKILL.md
cat <<'EOF'
[Memory MCP active] Load context before working, save before stopping. See memory-agent skill for full protocol.
EOF

exit 0
