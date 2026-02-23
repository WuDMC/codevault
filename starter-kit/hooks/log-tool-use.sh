#!/bin/bash
# log-tool-use.sh - Log Bash tool usage to session JSONL (async)
# Hook: PostToolUse (matcher: Bash)

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

[ -d "$LOG_DIR" ] || exit 0

jq -n \
  --arg event "tool_use" \
  --arg timestamp "$TIMESTAMP" \
  --arg tool "$TOOL_NAME" \
  --arg command "$COMMAND" \
  '{event: $event, timestamp: $timestamp, tool: $tool, command: $command}' \
  >> "$SESSION_LOG"

exit 0
