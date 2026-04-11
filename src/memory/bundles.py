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

BUNDLE_VERSION = 4

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
LAYER 1 — EPHEMERAL (in-conversation work tracking)
  Tool: TaskCreate / TaskUpdate / TaskList
  Scope: current conversation only. Dies with the session.
  Use for: "right now I'm doing X, then Y, then Z"

LAYER 2 — EPIC (multi-session work tracking)
  Tool: memory_epic_add / memory_epic_get / memory_epic_find / memory_epic_update
  Scope: project, persists across sessions. Markdown checklist inside.
  Use for: features, refactors, bug investigations that span sessions

LAYER 3 — LONG-TERM (project knowledge base)
  Tool: memory_save / memory_search / memory_context
  Scope: project, searchable across all projects. Forever.
  Use for: decisions, bug root causes, patterns, learnings
```

---

## Session Start — MANDATORY, PROACTIVE, IMMEDIATE

**BEFORE your first response** to the user, you MUST execute these steps. Do not wait for the user to ask. Do not skip any step. Do not start working until all steps are done.

**Step 1 — Load context (ALWAYS, FIRST):**
```
memory_context(project="{{project_name}}", limit=10)
```
This returns recent memories AND active epics (including auto-created Backlog).

**Step 2 — Identify your epic (ALWAYS, BEFORE ANY WORK):**

| Situation | Action |
|-----------|--------|
| User said a ticket name ("work on AUTH-123") | `memory_epic_find(ticket="AUTH-123")` |
| Context shows exactly 1 active epic (not Backlog) | Use it — say "I'll continue epic #N: Title" |
| Context shows multiple active epics | Ask: "Which epic? [list them]" — **do not guess** |
| User said "adhoc" / "just fix this" / no ticket | Use the Backlog epic from context |
| You were spawned as a subagent with epic_id in prompt | Use the epic_id from your prompt |

**You MUST work within an epic. Do not start coding without one.**

**Step 3 — Load epic checklist:**
```
memory_epic_get(epic_id=<id from step 2>)
```
Read the checklist. Know what's done, what's next.

**Step 4 — Search if needed:**
If the user's request relates to a specific topic, search for prior decisions:
```
memory_search(query="<relevant topic>")
```
If any result has `has_details=true`, call `memory_details(memory_id)`.

---

## Layer 1: TaskCreate (in-session progress)

**Use when:** 3+ discrete steps in the current response.

```
TaskCreate(subject="Implement JWT issuer", activeForm="Implementing JWT issuer")
TaskUpdate(taskId="1", status="in_progress")
# ... do the work ...
TaskUpdate(taskId="1", status="completed")  ← IMMEDIATELY when done, do not batch
```

**Do NOT** use TaskCreate for work that should survive the session — that's epics.
**Do NOT** pass tasks to subagents via TaskList — they can't see them. Pass via prompt.

---

## Layer 2: memory_epic_* (multi-session work)

Every piece of work belongs to an epic. There are no standalone TODOs.

### Creating an epic (architect/user role)

```
memory_epic_add(
  project="{{project_name}}",
  title="Refactor auth module to JWT",
  ticket="AUTH-123",
  description="- [ ] Audit session usage\\n- [ ] Design JWT schema\\n- [ ] Implement token issuer\\n- [ ] Update tests"
)
```
Create when: there's a ticket, OR work has 3+ steps, OR it will span sessions.

### Finding an epic

```
memory_epic_find(ticket="AUTH-123")       # by ticket name
memory_epic_get(epic_id=42)               # by ID (when you know it)
```

### Updating the checklist (PROACTIVE — do this as you complete steps)

Rewrite the full checklist with updated marks. **Do this after completing each major step, not just at session end.**

```
memory_epic_update(
  epic_id=42,
  description="- [x] Audit session usage\\n- [x] Design JWT schema\\n- [ ] Implement token issuer\\n- [ ] Update tests"
)
```

### Closing an epic

When ALL checklist items are done:
```
memory_epic_update(epic_id=42, status="done")
```

### The Backlog epic

Every project has a Backlog epic (auto-created, ticket="_backlog"). Use for:
- Adhoc tasks without a ticket
- Quick fixes, micro-tasks
- "Just do it" work

Add items: `memory_epic_update(epic_id=<backlog_id>, description="<existing>\\n- [ ] New item")`

### Role rules

| Role | Can create epics | Can list all epics | Must be assigned epic |
|------|-----------------|-------------------|----------------------|
| **User/Architect** | Yes | Yes (`memory_epic_list`) | No — they assign |
| **Developer** | Only Backlog items | **No** — only works on assigned epic | **Yes** — ask if none given |
| **Reviewer** | No | Can read assigned epic | Reads, doesn't manage |

---

## Layer 3: memory_save (knowledge base)

**Use when:** work is done and the *reasoning* should survive.

```
memory_save(
  title="Chose jose library for JWT signing",
  what="Selected jose over jsonwebtoken for JWT implementation",
  why="jose supports EdDSA and has better TypeScript types",
  impact="All auth endpoints now use jose for token signing",
  tags=["auth", "jwt"],
  category="decision",
  related_files=["src/auth/jwt.ts"],
  project="{{project_name}}",
  source="claude-code",
  agent="developer",
  epic_id=42
)
```

**ALWAYS pass `epic_id`** — auto-adds the ticket as a tag.

**Categories:** `decision` | `bug` | `pattern` | `setup` | `learning` | `context`

### The `source` and `agent` fields

**source** — which client/IDE:
- `"claude-code"` — Claude Code CLI or desktop
- `"cursor"` — Cursor IDE
- `"codex"` — Codex CLI
- `"api"` — custom agent via API

**agent** — your role in this session:
- `"interactive"` — human is driving (default for CLI)
- `"developer"` — writing/modifying code
- `"architect"` — designing systems, planning epics
- `"reviewer"` — checking correctness

### ALWAYS save (proactively, immediately after the event):
- Architectural or design decisions (with alternatives considered)
- Bug root causes and fixes (the *why*, not just "fixed it")
- Non-obvious patterns or gotchas
- Infrastructure, tooling, or configuration changes
- User corrections or clarified requirements
- **After every successful commit** — save the rationale
- **After tests pass/fail** — save what you learned
- **After resolving a bug** — save root cause + fix
- **When user confirms a design choice** — save with alternatives

### NEVER save:
- Trivial changes (typos, formatting)
- Info obvious from reading the code
- Duplicates (search first!)

---

## Session End — MANDATORY

Before ending ANY session where you did meaningful work:

1. **Update epic checklist** — mark completed steps, add newly discovered steps
2. **Save knowledge** — `memory_save` for each distinct decision/bug/pattern (with `epic_id`)
3. **Close epic if done** — `memory_epic_update(epic_id, status="done")` if all steps complete
4. **Complete layer 1 tasks** — mark any in-flight TaskCreate as `completed` or `deleted`

The session-stop hook will **block you from stopping** if you did >2 tool uses but never called `memory_save` or `memory_epic_update`. Save your work first.

---

## Subagents and Multi-Agent Workflows

### Key facts about subagents

- **Subagents inherit MCP servers** from the parent — they CAN call memory_save, memory_epic_*, memory_search directly.
- **Subagents do NOT inherit skills** — the parent must include memory instructions in the subagent's prompt.
- **Subagents do NOT see parent's TaskList** — pass work via prompt, not tasks.
- **Subagents in worktrees** (`isolation: "worktree"`) still access the same MCP servers.

### How to spawn a subagent with memory access

The parent MUST include epic context in the subagent's prompt:

```
Agent(
  prompt="You are a developer working on epic #42 (ticket AUTH-123).
    Your task: implement the JWT token issuer (step 3 of the epic checklist).

    MEMORY PROTOCOL:
    - Call memory_epic_get(epic_id=42) to see full checklist
    - Call memory_search(query='JWT auth') for prior decisions
    - When done, call memory_save(title=..., epic_id=42, agent='developer')
    - Update checklist: memory_epic_update(epic_id=42, description='...')

    Do NOT call memory_epic_list or create new epics.",
  subagent_type="general-purpose"
)
```

### Multi-agent handoff pattern

When architect creates work for developer subagents:

```
1. Architect: memory_epic_add(title="...", ticket="X", description="checklist")
   → gets epic_id

2. Architect: spawns Agent with prompt containing:
   - epic_id
   - which checklist step to work on
   - memory protocol instructions (above)
   - role = "developer"

3. Developer subagent:
   - memory_epic_get(epic_id) → reads checklist
   - does the work
   - memory_save(epic_id=epic_id, agent="developer") → saves decisions
   - memory_epic_update(epic_id, description="updated checklist")
   - returns result to parent

4. Architect: receives result, may spawn next subagent for next step
```

### Agent teams (parallel agents)

When using agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`):
- Teammates load MCP servers from project settings (`.mcp.json`), NOT from subagent definition
- Teammates DO NOT inherit skills from subagent YAML — they load from `.claude/skills/`
- Each teammate should call `memory_context()` independently at their start
- Use epic_id to coordinate: all teammates on the same epic see the same checklist

### Autonomous / scheduled agents

For agents running without user interaction (via `/schedule` or cron):
- MUST call `memory_context()` at start — no user to tell them the epic
- Should have epic_id hardcoded in their prompt or find it via `memory_epic_find(ticket="...")`
- MUST call `memory_save()` before finishing — no human will remind them
- Use `source="api"` and `agent="autonomous:<role>"` (e.g. `"autonomous:reviewer"`)

---

## Decision Tree

```
Is this work happening RIGHT NOW?
├── YES → TaskCreate if 3+ steps, otherwise just do it
└── NO
    ├── Is it a closed decision/learning/bug fix?
    │   └── YES → memory_save(epic_id=...)
    └── Is it work for later in this epic?
        └── YES → memory_epic_update(checklist)
```

---

## Rules

1. **Load context FIRST.** Call `memory_context()` before your first response. No exceptions.
2. **Identify your epic SECOND.** Do not start working without an epic_id.
3. **Save PROACTIVELY.** Don't wait for session end — save after each major milestone.
4. **Update checklist AS YOU GO.** Not just at the end.
5. **Write for a stranger.** Every memory should be useful to an agent with zero context.
6. **Never save secrets.** No API keys, tokens, passwords. Use `<redacted>` tags.
7. **Search before saving.** Avoid duplicates.
8. **One memory per event.** Don't bundle unrelated decisions.
9. **Always pass epic_id.** Links memory to epic, auto-tags with ticket.
10. **Subagents: include protocol in prompt.** They inherit MCP but NOT skills.
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
