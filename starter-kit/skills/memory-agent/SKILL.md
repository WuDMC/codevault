---
name: memory-agent
description: Persistent memory integration for coding agents. You MUST load context at session start and save memories before session end. This is not optional.
---

# Memory Agent Protocol

You have persistent memory via the Memory MCP server. This memory persists across sessions and is shared with other agents working on this project.

## Session Start — MANDATORY

Before doing ANY work:

1. Call `memory_context` with `project` set to the current project name and `limit=10` — this returns full content (what, why, impact) for recent memories
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
  project="<project-name>",
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

<!-- PROJECT-SPECIFIC CHECKPOINTS
Add your project-specific checkpoints here. Examples:
- After `tb build` succeeds with schema changes (Tinybird)
- After `npm run build` passes (Node.js)
- After `terraform apply` completes (Infrastructure)
- After `docker compose up` works (Docker)
-->

## Rules

- Load context before working. Save before finishing. No exceptions.
- Write memories for a future agent with zero context about this session.
- Never include API keys, tokens, secrets, or credentials in memories.
- Wrap sensitive values in `<redacted>` tags.
- One memory per distinct decision or event. Do not bundle unrelated things.
- Search before saving to avoid duplicates.
