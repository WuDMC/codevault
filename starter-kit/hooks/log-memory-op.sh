#!/bin/bash
# log-memory-op.sh - Log Memory MCP operations to session JSONL (async)
# Hook: PostToolUse (matcher: mcp__memory__*)

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

[ -d "$LOG_DIR" ] || exit 0

jq -n \
  --arg event "memory_op" \
  --arg timestamp "$TIMESTAMP" \
  --arg tool "$TOOL_NAME" \
  --argjson input "$TOOL_INPUT" \
  '{event: $event, timestamp: $timestamp, tool: $tool, input: $input}' \
  >> "$SESSION_LOG"

exit 0
