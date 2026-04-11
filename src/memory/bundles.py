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

BUNDLE_VERSION = 3

# ---------------------------------------------------------------------------
# Canonical SKILL.md (MCP-based, universal)
# ---------------------------------------------------------------------------

SKILL_MD = """\
---
name: memory-agent
description: Persistent memory and epic-based work tracking for coding agents. You MUST load context at session start, work within an epic, and save memories before session end. This is not optional.
---

# Memory Agent Protocol

You have three distinct layers of work tracking. **Each solves a different problem — do not mix them up.**

## The Three Layers

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1 — EPHEMERAL (in-conversation work tracking)          │
│   Tool: TaskCreate / TaskUpdate / TaskList                   │
│   Scope: current conversation only                           │
│   Lifetime: dies with the session                            │
│   Use for: "right now I'm doing X, then Y, then Z"           │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ LAYER 2 — EPIC (multi-session work tracking)                 │
│   Tool: memory_epic_* (add, get, find, list, update)         │
│   Scope: project, persists across sessions                   │
│   Lifetime: until done or cancelled                          │
│   Structure: Markdown checklist inside each epic             │
│   Use for: features, refactors, bugs that span sessions      │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ LAYER 3 — LONG-TERM (project knowledge base)                 │
│   Tool: memory_save / memory_search / memory_context         │
│   Scope: project (searchable across all projects)            │
│   Lifetime: forever                                          │
│   Use for: decisions, bug root causes, patterns, learnings   │
└──────────────────────────────────────────────────────────────┘
```

---

## Session Start — MANDATORY

Before doing ANY work:

1. **Load context:** `memory_context(project="{{project_name}}", limit=10)` — returns recent memories + active epics
2. **Identify your epic:**
   - If user specified a ticket → `memory_epic_find(ticket="AUTH-123")`
   - If context shows 1 active epic (excluding Backlog) → use it
   - If multiple active epics → ask the user which one
   - If user says "adhoc" or small task → use the Backlog epic (auto-created)
   - **You MUST work within an epic. Do not start without one.**
3. **Load epic checklist:** `memory_epic_get(epic_id)` — see current progress
4. **Search for specifics** (only if needed): `memory_search(query="<topic>")`
5. **Fetch details:** if any result has `has_details=true`, call `memory_details(memory_id)`

Do not skip these steps.

---

## Layer 1: TaskCreate / TaskUpdate / TaskList

**Use when:** the current request requires 3+ discrete steps and you want to show progress.

**Lifecycle:**
1. At task start: `TaskCreate(subject="...", description="...", activeForm="...")`
2. When starting work: `TaskUpdate(taskId="1", status="in_progress")`
3. When done: `TaskUpdate(taskId="1", status="completed")` — **immediately, do not batch**
4. End of session: do nothing — tasks die with the conversation

**DO NOT:**
- Use TaskCreate for things that should survive the session — that's layer 2 (epics)
- Use TaskCreate for trivial single-step work
- Pass tasks to subagents via the task list — **subagents do not see parent tasks**

---

## Layer 2: memory_epic_* (multi-session work)

Every piece of work belongs to an epic. There are no standalone TODOs.

### Creating an epic

```
memory_epic_add(
  project="{{project_name}}",
  title="Refactor auth module to JWT",
  ticket="AUTH-123",           # optional — links to external tracker
  description="- [ ] Audit session usage\\n- [ ] Design JWT schema\\n- [ ] Implement token issuer\\n- [ ] Update tests"
)
```

### Finding an epic by ticket

```
memory_epic_find(ticket="AUTH-123")
```

### Updating the checklist

When you complete a step, rewrite the full checklist with updated marks:

```
memory_epic_update(
  epic_id=42,
  description="- [x] Audit session usage\\n- [x] Design JWT schema\\n- [ ] Implement token issuer\\n- [ ] Update tests"
)
```

### Closing an epic

When all checklist items are done:

```
memory_epic_update(epic_id=42, status="done")
```

### The Backlog epic

Every project has a special Backlog epic (auto-created, ticket="_backlog"). Use it for:
- Adhoc tasks that don't have a ticket
- Quick fixes and micro-tasks
- Work the user says "just do it, no ticket needed"

Add items to Backlog by updating its checklist:
```
memory_epic_update(epic_id=<backlog_id>, description="<existing checklist>\\n- [ ] New adhoc item")
```

### Role rules for epics

- **User** tells architect/developer which ticket/epic to work on
- **Architect** creates epics, plans checklists, assigns work
- **Developer** MUST work within a given epic. **Do NOT call `memory_epic_list`** — you work only on the epic assigned to you. If no epic was assigned, ask the user.
- If the user doesn't specify a ticket → ask: "Which epic should I work on, or is this an adhoc task?"

### When to create an epic

- **Always** if there's a ticket (AUTH-123, github#45, etc.)
- **When** work has 3+ steps or will span multiple sessions
- **Never** for truly trivial work — use Backlog instead

---

## Layer 3: memory_save (knowledge base)

**Use when:** work is done and the *reasoning* should survive. Save the decision, not the diff.

```
memory_save(
  title="Short descriptive title",
  what="What happened or was decided",
  why="Reasoning behind it",
  impact="What changed as a result",
  tags=["tag1", "tag2"],
  category="decision",
  related_files=["path/to/file"],
  project="{{project_name}}",
  source="claude-code",
  agent="developer",
  epic_id=42                    # links memory to epic, auto-adds ticket as tag
)
```

Categories: `decision`, `bug`, `pattern`, `setup`, `learning`, `context`.

**Always pass `epic_id`** when working within an epic. This links the memory to the epic and auto-adds the ticket as a tag.

### ALWAYS save (high signal):
- Architectural or design decisions (with alternatives considered)
- Bug root causes and fixes (not just "fixed it" — the *why*)
- Non-obvious patterns or gotchas discovered
- Infrastructure, tooling, or configuration changes
- User corrections or clarified requirements

### NEVER save (noise):
- Trivial changes (typo fixes, formatting)
- Information already obvious from reading the code
- Duplicate of an existing memory (search first!)

### Checkpoint saves

1. **After a successful commit** — save the decision or change rationale
2. **After tests pass/fail** — save test configuration decisions or discovered issues
3. **After resolving a bug** — save root cause, fix, and what you learned
4. **When user confirms a design choice** — save with alternatives considered

---

## Decision Tree: which layer?

```
Is this work happening RIGHT NOW in this response?
├── YES → Layer 1 (TaskCreate) if 3+ steps, otherwise nothing
└── NO
    ├── Is it a closed decision/learning/bug fix?
    │   └── YES → Layer 3 (memory_save with epic_id)
    └── Is it work for later in this epic?
        └── YES → Update epic checklist (memory_epic_update)
```

**Examples:**

| Situation | Layer | Tool |
|-----------|-------|------|
| "I'll create the file, then add the function, then write the test" | 1 | TaskCreate (3 tasks) |
| "We decided to use JWT instead of sessions" | 3 | memory_save(epic_id=42) |
| "Still need to update tests, will do next session" | 2 | memory_epic_update(checklist) |
| "Renaming this variable" | none | just do it |
| "Bug root cause: cache TTL was 0" | 3 | memory_save(category="bug", epic_id=42) |
| "User wants dark mode but not now" | 2 | add to Backlog checklist |
| "Building this feature in 5 steps" | 1 | TaskCreate (5 tasks) |

---

## Session End — MANDATORY

Before ending your response to ANY task that involved changes, debugging, deciding, or learning:

1. **Update epic checklist** (layer 2): mark completed steps, add new discovered steps
2. **Save knowledge** (layer 3): `memory_save` for every distinct decision/bug/pattern (with `epic_id`)
3. **Close epic if done**: `memory_epic_update(epic_id, status="done")` if all steps complete
4. **Mark layer 1 tasks complete**: any in-flight TaskCreate items should be `completed` or `deleted`

---

## Agent Roles

Use the `agent` field on `memory_save`:

- **developer**: Writing/modifying code, fixing bugs
- **architect**: Designing systems, choosing patterns, schema evolution
- **reviewer**: Reviewing code, checking correctness

Filter by agent: `memory_search(query="...", agent="architect")`

---

## Subagents

- **Subagents do NOT see parent tasks** — their TaskList is independent
- **Subagents DO see the same MCP memory** — they can call `memory_save`, `memory_epic_*` directly
- **Pass work via prompt**, not via task list
- **Parent owns the task tracking** — use TaskCreate in parent to track each subagent

---

## Rules

- Load context and identify your epic before working. Update epic and save memories before finishing. No exceptions.
- Write memories for a future agent with zero context about this session.
- Never include API keys, tokens, secrets, or credentials in memories.
- Wrap sensitive values in `<redacted>` tags.
- One memory per distinct decision or event.
- Search before saving to avoid duplicates.
- Always work within an epic. No standalone TODOs.
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
#
# Recognizes both layer 2 (memory_epic_update) and layer 3 (memory_save) as
# "saving work". If meaningful work was done but neither happened, blocks
# the stop and asks the agent to update the epic and/or save memories.

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

# Count meaningful work and persistence operations
MEMORY_SAVES=$(grep -c 'mcp__memory__memory_save' "$SESSION_LOG" 2>/dev/null || echo "0")
EPIC_UPDATES=$(grep -c 'mcp__memory__memory_epic_update' "$SESSION_LOG" 2>/dev/null || echo "0")
TOOL_USES=$(grep -c '"event":"tool_use"' "$SESSION_LOG" 2>/dev/null || echo "0")
PERSISTED=$((MEMORY_SAVES + EPIC_UPDATES))

# If meaningful work was done but nothing was persisted, block stop
if [ "$TOOL_USES" -gt 2 ] && [ "$PERSISTED" -eq 0 ]; then
  jq -n --arg project "$PROJECT_NAME" '{
    "decision": "block",
    "reason": ("You performed meaningful work this session but did not call memory_save or memory_epic_update. Before stopping:\\n1. Update your epic checklist with progress: memory_epic_update(epic_id=..., description=\\"...\\")\\n2. Save decisions/bugs/patterns: memory_save(project=\\"" + $project + "\\", epic_id=..., source=\\"claude-code\\", ...)\\n3. If nothing worth saving, say so and stop again.")
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
