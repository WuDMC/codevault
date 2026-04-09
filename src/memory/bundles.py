"""Canonical skill bundles served by the MCP server.

Each bundle contains skills, hooks, settings templates, and MCP config
for a specific agent type. The server exposes these via REST endpoints
and the CLI fetches them during `memory install`.
"""

import hashlib
import json

# ---------------------------------------------------------------------------
# Bundle version — increment when any content changes
# ---------------------------------------------------------------------------

BUNDLE_VERSION = 1

# ---------------------------------------------------------------------------
# Canonical SKILL.md (MCP-based, universal)
# ---------------------------------------------------------------------------

SKILL_MD = """\
---
name: memory-agent
description: Persistent memory integration for coding agents. You MUST load context at session start and save memories before session end. This is not optional.
---

# Memory Agent Protocol

You have persistent memory via the Memory MCP server. This memory persists across sessions and is shared with other agents working on this project.

## Session Start — MANDATORY

Before doing ANY work:

1. Call `memory_context(project="{{project_name}}", limit=10)` — returns full content (what, why, impact) for recent memories
2. Use `memory_search` only when you need memories from other projects, older history, or a specific topic not in the context
3. If a memory has `has_details=true`, call `memory_details(memory_id)` for the extended body
4. Review loaded context before proceeding — prior sessions may have captured decisions that affect your current task

Do not skip this step. Prior sessions contain decisions, bugs, and context that directly affect your current task.

## Session End — MANDATORY

Before ending your response to ANY task that involved changes, debugging, deciding, or learning, you MUST save a memory:

```
memory_save(
  title="Short descriptive title",
  what="What happened or was decided",
  why="Reasoning behind it",
  impact="What changed as a result",
  tags=["tag1", "tag2", "tag3"],
  category="decision",
  related_files=["path/to/file1", "path/to/file2"],
  project="{{project_name}}",
  source="claude-code",
  agent="developer"
)
```

Categories: `decision`, `bug`, `pattern`, `setup`, `learning`, `context`.

## Agent Roles

Use the `agent` field to tag memories by role:

- **developer**: Writing/modifying code, fixing bugs
- **architect**: Designing systems, choosing patterns, schema evolution
- **reviewer**: Reviewing code, checking correctness, running comparison tests

Filter by agent when searching: `memory_search(query="...", agent="architect")`

## When to Save

### ALWAYS save (high signal):
- Architectural or design decisions (with alternatives considered)
- Bug root causes and fixes
- Non-obvious patterns or gotchas discovered
- Infrastructure, tooling, or configuration changes
- User corrections or clarified requirements
- Anything a future agent with zero context would need to know

### NEVER save (noise):
- Trivial changes (typo fixes, formatting)
- Information already obvious from reading the code
- Duplicate of an existing memory (search first!)

## Checkpoint Saves

Save at these natural checkpoints during work:

1. **After a successful commit** — save the decision or change rationale
2. **After tests pass/fail** — save test configuration decisions or discovered issues
3. **After resolving a bug** — save root cause, fix, and what you learned
4. **When user confirms a design choice** — save with alternatives considered

## Rules

- Load context before working. Save before finishing. No exceptions.
- Write memories for a future agent with zero context about this session.
- Never include API keys, tokens, secrets, or credentials in memories.
- Wrap sensitive values in `<redacted>` tags.
- One memory per distinct decision or event. Do not bundle unrelated things.
- Search before saving to avoid duplicates.
"""

# ---------------------------------------------------------------------------
# Hook scripts
# ---------------------------------------------------------------------------

HOOK_SESSION_START = """\
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
echo "{\\"event\\":\\"session_start\\",\\"timestamp\\":\\"$TIMESTAMP\\",\\"session_id\\":\\"$SESSION_ID\\"}" >> "$SESSION_LOG"

# Cleanup logs older than 30 days
find "$LOG_DIR" -name "session-*.jsonl" -mtime +30 -delete 2>/dev/null

# Short reminder — full protocol is in .claude/skills/memory-agent/SKILL.md
cat <<'REMINDER'
[Memory MCP active] Load context before working, save before stopping. See memory-agent skill for full protocol.
REMINDER

exit 0
"""

HOOK_SESSION_STOP = """\
#!/bin/bash
# session-stop.sh - Smart save checkpoint at session end
# Hook: Stop (sync) — can block stop if work is unsaved

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // "false"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

LOG_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
SESSION_LOG="$LOG_DIR/session-${SESSION_ID}.jsonl"

# Auto-detect project name from directory
PROJECT_NAME=$(basename "${CLAUDE_PROJECT_DIR:-.}")

# Log the stop event
[ -d "$LOG_DIR" ] && echo "{\\"event\\":\\"session_stop\\",\\"timestamp\\":\\"$TIMESTAMP\\"}" >> "$SESSION_LOG"

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
    "reason": ("You performed meaningful work this session but have not saved any memories. Before stopping, please:\\n1. Review what you accomplished\\n2. Call memory_save for any decisions, bugs found, or patterns learned (project=\\"" + $project + "\\", source=\\"claude-code\\")\\n3. If nothing worth saving, say so and stop again.")
  }'
  exit 0
fi

exit 0
"""

HOOK_LOG_PROMPT = """\
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

echo "{\\"event\\":\\"user_prompt\\",\\"timestamp\\":\\"$TIMESTAMP\\",\\"prompt\\":$(echo "$PROMPT" | jq -Rs .)}" >> "$SESSION_LOG"

exit 0
"""

HOOK_LOG_TOOL_USE = """\
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

jq -n \\
  --arg event "tool_use" \\
  --arg timestamp "$TIMESTAMP" \\
  --arg tool "$TOOL_NAME" \\
  --arg command "$COMMAND" \\
  '{event: $event, timestamp: $timestamp, tool: $tool, command: $command}' \\
  >> "$SESSION_LOG"

exit 0
"""

HOOK_LOG_MEMORY_OP = """\
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

jq -n \\
  --arg event "memory_op" \\
  --arg timestamp "$TIMESTAMP" \\
  --arg tool "$TOOL_NAME" \\
  --argjson input "$TOOL_INPUT" \\
  '{event: $event, timestamp: $timestamp, tool: $tool, input: $input}' \\
  >> "$SESSION_LOG"

exit 0
"""

HOOK_ON_COMMIT = """\
#!/bin/bash
# on-commit.sh - Remind agent to save memory after git commit
# Hook: PostToolUse (matcher: Bash) — runs alongside log-tool-use.sh

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_output // ""' 2>/dev/null)

# Only trigger on git commit commands
echo "$COMMAND" | grep -q 'git commit' || exit 0

# Only if commit succeeded (output contains [branch hash] pattern)
echo "$TOOL_OUTPUT" | grep -qE '\\[.+ [a-f0-9]+\\]' || exit 0

cat <<'EOF'
[Commit detected] If this commit contains a decision, bug fix, or architectural change, save a memory now with memory_save.
EOF

exit 0
"""

# ---------------------------------------------------------------------------
# Settings template (hooks config for Claude Code)
# ---------------------------------------------------------------------------

SETTINGS_HOOKS = {
    "SessionStart": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"',
                    "timeout": 10,
                }
            ]
        }
    ],
    "UserPromptSubmit": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/log-prompt.sh"',
                    "timeout": 5,
                }
            ]
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/log-tool-use.sh"',
                    "timeout": 5,
                },
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/on-commit.sh"',
                    "timeout": 5,
                },
            ],
        },
        {
            "matcher": "mcp__memory__.*",
            "hooks": [
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/log-memory-op.sh"',
                    "timeout": 5,
                }
            ],
        },
    ],
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-stop.sh"',
                    "timeout": 15,
                }
            ]
        }
    ],
}

# ---------------------------------------------------------------------------
# Gitignore lines to append
# ---------------------------------------------------------------------------

GITIGNORE_LINES = [
    ".claude/logs/",
    ".claude/settings.local.json",
]

# ---------------------------------------------------------------------------
# Bundle files map
# ---------------------------------------------------------------------------

_BUNDLE_FILES = {
    "skills/memory-agent/SKILL.md": {
        "content": SKILL_MD,
        "executable": False,
        "template": True,
    },
    "hooks/session-start.sh": {
        "content": HOOK_SESSION_START,
        "executable": True,
        "template": False,
    },
    "hooks/session-stop.sh": {
        "content": HOOK_SESSION_STOP,
        "executable": True,
        "template": False,
    },
    "hooks/log-prompt.sh": {
        "content": HOOK_LOG_PROMPT,
        "executable": True,
        "template": False,
    },
    "hooks/log-tool-use.sh": {
        "content": HOOK_LOG_TOOL_USE,
        "executable": True,
        "template": False,
    },
    "hooks/log-memory-op.sh": {
        "content": HOOK_LOG_MEMORY_OP,
        "executable": True,
        "template": False,
    },
    "hooks/on-commit.sh": {
        "content": HOOK_ON_COMMIT,
        "executable": True,
        "template": False,
    },
}


def _content_hash(files: dict) -> str:
    """Compute SHA-256 hash over all file contents in sorted order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(files[name]["content"].encode())
    return f"sha256:{h.hexdigest()}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_bundles() -> list[str]:
    """Return available bundle names."""
    return ["claude-code"]


def get_bundle(agent_type: str) -> dict | None:
    """Return the full bundle manifest for an agent type.

    Returns None if the agent type is not supported.
    """
    if agent_type != "claude-code":
        return None

    return {
        "name": "claude-code",
        "version": BUNDLE_VERSION,
        "content_hash": _content_hash(_BUNDLE_FILES),
        "files": _BUNDLE_FILES,
        "settings_hooks": SETTINGS_HOOKS,
        "mcp_config": {
            "type": "http",
            "url": "{{server_url}}/mcp",
            "headers": {
                "Authorization": "Bearer {{auth_token}}",
            },
        },
        "gitignore_lines": GITIGNORE_LINES,
    }
