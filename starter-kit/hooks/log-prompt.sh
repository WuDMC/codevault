#!/bin/bash
# log-prompt.sh - Log user prompts to session JSONL (async, never blocks)
# Hook: UserPromptSubmit

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

[ -d "$LOG_DIR" ] || exit 0

echo "{\"event\":\"user_prompt\",\"timestamp\":\"$TIMESTAMP\",\"prompt\":$(echo "$PROMPT" | jq -Rs .)}" >> "$SESSION_LOG"

exit 0
