#!/bin/bash
# session-stop.sh - Smart save checkpoint at session end
# Hook: Stop (sync) — can block stop if work is unsaved
#
# Logic:
# - If stop_hook_active=true (already blocked once) → always allow
# - If >2 tool uses and 0 memory_save calls → block stop, ask Claude to save
# - Otherwise → allow stop

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // "false"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

# Auto-detect project name from directory
PROJECT_NAME=$(basename "${CLAUDE_PROJECT_DIR:-.}")

# Log the stop event
[ -d "$LOG_DIR" ] && echo "{\"event\":\"session_stop\",\"timestamp\":\"$TIMESTAMP\"}" >> "$SESSION_LOG"

# If already continuing from a blocked stop, allow immediately
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# Guard: if log file doesn't exist, allow stop
[ -f "$SESSION_LOG" ] || exit 0

# Count meaningful work and memory saves
MEMORY_SAVES=$(grep -c 'mcp__memory__memory_save' "$SESSION_LOG" 2>/dev/null || echo "0")
TOOL_USES=$(grep -c '"event":"tool_use"' "$SESSION_LOG" 2>/dev/null || echo "0")

# If meaningful work was done but no memory save, block stop
if [ "$TOOL_USES" -gt 2 ] && [ "$MEMORY_SAVES" -eq 0 ]; then
  jq -n --arg project "$PROJECT_NAME" '{
    "decision": "block",
    "reason": ("You performed meaningful work this session but have not saved any memories. Before stopping, please:\n1. Review what you accomplished\n2. Call memory_save for any decisions, bugs found, or patterns learned (project=\"" + $project + "\", source=\"claude-code\")\n3. If nothing worth saving, say so and stop again.")
  }'
  exit 0
fi

exit 0
