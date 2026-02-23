#!/bin/bash
# on-commit.sh - Remind agent to save memory after git commit
# Hook: PostToolUse (matcher: Bash) — runs alongside log-tool-use.sh
#
# Detects successful git commits and nudges the agent to save a memory
# if the commit involved a meaningful change (decision, bug fix, etc.)

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_output // ""' 2>/dev/null)

# Only trigger on git commit commands
echo "$COMMAND" | grep -q 'git commit' || exit 0

# Only if commit succeeded (output contains [branch hash] pattern)
echo "$TOOL_OUTPUT" | grep -qE '\[.+ [a-f0-9]+\]' || exit 0

cat <<'EOF'
[Commit detected] If this commit contains a decision, bug fix, or architectural change, save a memory now with memory_save.
EOF

exit 0
