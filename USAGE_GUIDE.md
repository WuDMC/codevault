# CodeVault Usage Guide & Best Practices

Complete guide to using CodeVault effectively — what to save, how to search, how to structure memories, and common anti-patterns to avoid.

---

## Table of Contents

- [MCP Tools (4 total)](#mcp-tools)
- [CLI Commands](#cli-commands)
- [Memory Structure](#memory-structure)
- [Categories](#categories)
- [Tags Best Practices](#tags-best-practices)
- [Session Workflow](#session-workflow)
- [Search System](#search-system)
- [Multi-Agent Workflow](#multi-agent-workflow)
- [What to Save](#what-to-save)
- [What NOT to Save](#what-not-to-save)
- [Anti-Patterns](#anti-patterns)
- [Details Field](#details-field)
- [Redaction](#redaction)
- [Multi-User Notes](#multi-user-notes)

---

## MCP Tools

CodeVault exposes 4 MCP tools to agents:

| Tool | Purpose | Required params |
|------|---------|----------------|
| `memory_save` | Persist a memory with structured metadata | `title`, `what` |
| `memory_search` | Hybrid FTS + semantic search | `query` |
| `memory_context` | Load recent memories for current project | (none, auto-detects project) |
| `memory_details` | Fetch full details by memory ID | `memory_id` |

### memory_save

Saves a structured memory. Has built-in deduplication — if a new memory matches an existing one by >=70% on title+content, it updates the existing record instead of creating a duplicate (merges tags, appends details, re-embeds).

```
title         — Short title, max 60 chars (required)
what          — Main content, 1-2 sentences (required)
why           — Reasoning behind the decision or fix
impact        — What changed as a result
tags          — List of relevant tags
category      — decision | bug | pattern | learning | context
related_files — File paths involved
details       — Full context (stored separately, fetched via memory_details)
project       — Project name (auto-detected from cwd if omitted)
```

### memory_search

Hybrid search combining keyword (FTS) and semantic (vector) search. Uses a tiered strategy:

1. FTS search first (cheap, always works)
2. If >=3 results found — return them (skip embedding cost)
3. If <3 results — embed the query, run vector search, merge results (FTS 30% weight, vectors 70%)

```
query   — Search terms (required)
limit   — Max results (default: 5)
project — Filter to specific project
```

### memory_context

Loads recent memories for the current project. Uses no embeddings (just recent records). Intended for session start.

```
project — Project name (auto-detected from cwd)
limit   — Max memories (default: 10)
```

### memory_details

Fetches the full `details` field for a memory. Use when `memory_search` or `memory_context` returns a memory with `has_details=true`.

```
memory_id — Full UUID or prefix (at least 8 chars)
```

---

## CLI Commands

### Core Commands

| Command | Description |
|---------|-------------|
| `memory init` | Initialize vault / create PG tables |
| `memory save --title "..." --what "..."` | Save a memory (see all options below) |
| `memory search "query"` | Hybrid search (`--limit`, `--project`, `--source`) |
| `memory details <id>` | Full details for a memory |
| `memory delete <id>` | Delete by ID or prefix |
| `memory context` | Project context (`--project`, `--limit`, `--semantic`, `--fts-only`, `--format`) |
| `memory reindex` | Rebuild vectors after changing embedding provider |
| `memory sessions` | List session files (`--limit`, `--project`) |

### Save Options

```bash
memory save \
  --title "Short title"              # required, max 60 chars
  --what "What happened"             # required
  --why "Why it matters"             # optional
  --impact "What changed"            # optional
  --tags "tag1,tag2"                 # comma-separated
  --category decision                # decision|bug|pattern|learning|context
  --related-files "src/db.py"        # comma-separated paths
  --details "Full context..."        # inline details
  --details-file notes.md            # OR read details from file
  --details-template                 # scaffold structured details template
  --source "claude-code"             # agent name
  --project "my-project"             # auto-detected from cwd if omitted
```

### Config Commands

| Command | Description |
|---------|-------------|
| `memory config` | Show current config (API keys redacted) |
| `memory config init` | Generate starter `config.yaml` |
| `memory config set-home <path>` | Set persistent MEMORY_HOME |
| `memory config clear-home` | Reset MEMORY_HOME to default |

### Agent Setup Commands

| Command | Description |
|---------|-------------|
| `memory setup claude-code` | Install MCP config for Claude Code |
| `memory setup cursor` | Install for Cursor |
| `memory setup codex` | Install for Codex |
| `memory setup opencode` | Install for OpenCode |
| `memory uninstall <agent>` | Remove integration |

All setup commands support `--project` to install per-project instead of globally.

### Multi-User Commands (PostgreSQL only)

| Command | Description |
|---------|-------------|
| `memory user add <name>` | Create user, prints auth token |
| `memory user list` | List all users |

### MCP Server

| Command | Description |
|---------|-------------|
| `memory mcp` | Start stdio server (local) |
| `memory mcp --transport sse --port 8420 --host 0.0.0.0` | Start SSE server (remote) |

---

## Memory Structure

Each memory has these fields:

```
id             — UUID, auto-generated
title          — Short descriptive title (max 60 chars)
what           — Main content: what happened or was decided (REQUIRED)
why            — Reasoning behind the decision or fix
impact         — What changed as a result
tags           — List of tags (case-insensitive dedup)
category       — One of: decision, bug, pattern, learning, context
project        — Project name
details        — Long-form context (stored separately)
related_files  — List of file paths
source         — Client/IDE (claude-code, cursor, codex)
agent          — Agent role (architect, developer, reviewer, orchestrator)
created_at     — Timestamp
updated_at     — Timestamp
embedding      — Vector (1536 dims for OpenAI, varies for Ollama)
```

---

## Categories

Use the right category — it affects how memories are grouped and displayed:

| Category | When to use | Example |
|----------|-------------|---------|
| `decision` | Architectural choice, "why X over Y" | "Chose PostgreSQL over SQLite for multi-user support" |
| `bug` | Bug fix with root cause + solution | "FTS params were doubled in PG query causing empty results" |
| `pattern` | Reusable gotcha, recurring trap | "MCP SSE requires connect_sse() at app level, not per-request" |
| `learning` | Non-obvious discovery | "Python 3.14 breaks sqlite-vec on ARM Macs" |
| `context` | Infrastructure, config, environment | "Deployed to VM instance-wu-2, port 8420, PG 18.2" |

### Rules of thumb

- If you **chose between options** → `decision`
- If you **fixed something broken** → `bug`
- If you'd **warn another developer** → `pattern`
- If you **discovered something surprising** → `learning`
- If it's about **setup or environment** → `context`

---

## Tags Best Practices

### Good tags — specific, reusable, searchable

```
postgresql, docker, sse, mcp, auth, deployment
python, fastmcp, pgvector, nginx, openai
config, migration, testing, performance
```

### Bad tags — too generic or redundant

| Bad tag | Why it's bad |
|---------|-------------|
| `important` | Everything you save should be important |
| `misc`, `stuff`, `other` | Unsearchable, adds no signal |
| `todo` | Use a task tracker, not memory |
| `bug-fix-2026-02-22` | Date is already in `created_at` |
| `fix` | Too vague — what was fixed? |
| `update` | What was updated? |

### Tag conventions

- Use lowercase: `postgresql` not `PostgreSQL`
- Use singular: `docker` not `dockers`
- Use the technology name: `nginx` not `reverse-proxy`
- 2-5 tags per memory is the sweet spot
- Reuse existing tags — check with `memory search` before inventing new ones

---

## Session Workflow

### Session Start (MANDATORY)

```
1. memory_context(project="your-project")
   → Loads last 10 memories for this project

2. memory_search("topic relevant to current task")
   → Search for specific prior context

3. memory_details(memory_id="abc12345")
   → Fetch full details if has_details=true
```

**Never skip this.** Prior sessions contain decisions and bugs that directly affect current work. Without context, agents repeat mistakes and re-discover known patterns.

### During Work

Search as needed when you encounter related topics:

```
memory_search("authentication")
memory_search("docker deployment")
```

### Session End (MANDATORY)

Save everything significant that happened. One memory per topic, not one giant dump.

```
memory_save(
  title="Fixed PG FTS params duplication",
  what="FTS search params list had query and embedding doubled",
  why="PG %s placeholders require exact param count match",
  impact="Search now returns correct results on PostgreSQL backend",
  tags=["postgresql", "fts", "search"],
  category="bug",
  related_files=["src/memory/db_pg.py"],
  details="Context: ..."
)
```

---

## Search System

### How hybrid search works

```
Query → FTS search (keyword matching, always works)
         ↓
     >=3 results? → Return them (skip embedding cost)
         ↓ no
     Embed query → Vector search → Merge weighted results
                                    (FTS 30% + Vectors 70%)
```

### Implications for writing good memories

- **Keywords matter most.** FTS is the primary search path. Use clear, specific terms in `title`, `what`, `why`, and `tags`.
- **Semantic search is a fallback.** It only kicks in when FTS finds fewer than 3 results.
- **Tags are indexed.** They're part of the FTS index, so good tags improve search.

### Search tips

```bash
# Broad search
memory search "authentication"

# Scoped to project
memory search "authentication" --project myapp

# Increase results
memory search "deployment" --limit 10
```

---

## Multi-Agent Workflow

CodeVault supports multiple agent roles working on the same project. Each agent saves memories with its role, and can filter to see only its own or all agents' memories.

### Isolation hierarchy

```
user (den / maryna)                         ← PG: WHERE user_id = X
  └── project (codevault / geo-roulette)    ← WHERE project = X
       └── agent (architect / developer)    ← WHERE agent = X
```

All three filters are optional and combinable.

### `agent` vs `source`

| Field | Purpose | Examples |
|-------|---------|---------|
| `source` | Which client/IDE saved the memory | `claude-code`, `cursor`, `codex` |
| `agent` | Which agent role saved the memory | `architect`, `developer`, `reviewer`, `orchestrator` |

These are independent fields. An architect agent running in Claude Code would save with `source="claude-code", agent="architect"`.

### Saving with agent role

**MCP tool:**
```
memory_save(
  title="Chose event-driven architecture",
  what="Selected event-driven pattern over request-response",
  agent="architect",
  source="claude-code",
  ...
)
```

**CLI:**
```bash
memory save \
  --title "Chose event-driven architecture" \
  --what "Selected event-driven pattern over request-response" \
  --agent architect \
  --source claude-code
```

### Searching by agent

**See only architect's decisions:**
```
memory_search(query="architecture", agent="architect")
```

**See all agents' memories (default):**
```
memory_search(query="architecture")
```

**Context for a specific agent:**
```
memory_context(project="codevault", agent="developer")
```

### Recommended agent roles

| Role | Saves | Reads |
|------|-------|-------|
| `architect` | Decisions, patterns, tradeoffs | Own memories |
| `developer` | Bugs, implementations, context | All agents |
| `reviewer` | Code review findings, patterns | All agents |
| `orchestrator` | Task breakdowns, coordination | All agents |
| `devops` | Infrastructure, deployment, config | Own + architect |

### Agent workflow example

```
1. Orchestrator breaks task into subtasks
   → memory_save(agent="orchestrator", category="context", ...)

2. Architect designs the approach
   → memory_save(agent="architect", category="decision", ...)

3. Developer implements
   → memory_context(agent="developer")    # sees all agents' memories
   → memory_search("auth", agent="architect")  # finds architect's decision
   → memory_save(agent="developer", category="bug", ...)

4. Reviewer checks the code
   → memory_search("auth")  # sees everything
   → memory_save(agent="reviewer", category="pattern", ...)
```

### Tips

- **Agents should save with their role** — always set `agent` when saving
- **Agents should read broadly** — omit `agent` filter when searching to see all context
- **Filter when needed** — use `agent` filter to reduce noise when you know which role's memories you want
- **Don't over-filter** — a developer benefits from seeing architect decisions

---

## What to Save

Save when ANY of these happen:

- **Made an architectural or design decision** — chose X over Y, with reasoning
- **Fixed a bug** — include root cause, symptoms, and solution
- **Discovered a non-obvious pattern** — something that would trip up another developer
- **Learned something about the codebase** — not obvious from reading the code
- **Set up infrastructure or tooling** — deployment, CI/CD, config changes
- **User corrected you or clarified a requirement** — preference or constraint
- **Encountered a gotcha** — library quirk, API behavior, compatibility issue

---

## What NOT to Save

- **Trivial changes** — typo fixes, formatting, renaming
- **Information obvious from code** — function signatures, imports
- **Duplicates** — always search before saving
- **Temporary state** — "currently debugging X" (that's a task, not a memory)
- **Content already in CLAUDE.md** — project instructions are loaded automatically
- **Raw code dumps** — save the *decision*, not the diff

---

## Anti-Patterns

| Anti-pattern | Why it's bad | Do this instead |
|-------------|-------------|-----------------|
| One giant memory per session | Can't search, can't reuse | One memory per topic |
| Skipping `why` and `impact` | "What" without "why" is useless in 3 months | Always fill why + impact |
| Generic tags (`important`, `misc`) | Unsearchable, adds no signal | Use specific technology/topic tags |
| Date-based tags (`feb-22`) | Date is in `created_at` | Don't duplicate metadata |
| Not loading context at session start | Agent repeats mistakes, re-discovers patterns | Always call `memory_context` first |
| Duplicating CLAUDE.md content | CLAUDE.md is auto-loaded, memories become noise | Save only what's NOT in docs |
| Saving raw diffs/code | Large, unsearchable, stale quickly | Save the decision + reasoning |
| Bundling unrelated topics | "Fixed X, added Y, configured Z" in one record | Split into 3 separate memories |
| Saving before searching | Creates duplicates | Search first, then save |

---

## Details Field

Use `details` for long-form context. It's stored separately and fetched on demand via `memory_details`.

### Recommended structure

```
Context:
  What was the situation when this came up.

Options considered:
  - Option A: description, pros/cons
  - Option B: description, pros/cons

Decision:
  What was chosen and why.

Tradeoffs:
  What we gave up or accepted.

Follow-up:
  What still needs to be done.
```

### When to use details

- Decisions with multiple options considered
- Bug fixes with complex root cause analysis
- Infrastructure setup with specific commands/configs
- Anything longer than 2-3 sentences

### CLI shortcuts

```bash
# Read details from a file
memory save --title "..." --what "..." --details-file notes.md

# Generate structured template
memory save --title "..." --what "..." --details-template
# Opens with pre-filled: Context, Options, Decision, Tradeoffs, Follow-up
```

---

## Redaction

CodeVault has 3-layer automatic redaction to prevent secrets from being stored:

### Layer 1: Explicit tags

Wrap sensitive content in `<redacted>` tags:

```
The API key is <redacted>sk-abc123</redacted>
→ Stored as: The API key is [REDACTED]
```

### Layer 2: Automatic pattern detection

These patterns are automatically redacted:

- Stripe keys (`sk_live_`, `sk_test_`, `pk_live_`, `pk_test_`)
- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`)
- AWS keys (`AKIA...`)
- JWTs (`eyJ...`)
- Private keys (`-----BEGIN ... PRIVATE KEY-----`)
- Fields named `password`, `secret`, `api_key`, `token` with values

### Layer 3: Custom patterns

Create `~/.memory/.memoryignore` with custom regex patterns:

```
# Company-specific patterns
INTERNAL_TOKEN_[A-Za-z0-9]+
my-company-secret-\d+
```

---

## Multi-User Notes

### User isolation

Every query is scoped by `user_id`. User A cannot see User B's memories, even on the same server.

### Authentication

SSE transport uses Bearer token auth:

```
Authorization: Bearer <64-char-hex-token>
```

The server resolves token → user_id, then scopes all DB queries with `WHERE user_id = X`.

### User management (admin, run on server)

```bash
# Create users
memory user add den       # prints token
memory user add maryna    # prints token

# List users
memory user list
```

### Client config (on each laptop)

```json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://YOUR_VM_IP:8420/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

---

## Quick Reference

### Save a decision

```bash
memory save \
  --title "Chose PostgreSQL over SQLite" \
  --what "Switched storage backend from SQLite to PostgreSQL+pgvector" \
  --why "Need multi-user support and remote access" \
  --impact "All queries now go to PG, user isolation via user_id" \
  --tags "postgresql,architecture,storage" \
  --category decision
```

### Save a bug fix

```bash
memory save \
  --title "Fixed FTS params duplication in PG" \
  --what "FTS search params list had query and embedding values doubled" \
  --why "PG requires exact match between %s placeholders and params count" \
  --impact "Search returns correct results on PostgreSQL backend" \
  --tags "postgresql,fts,search,bug" \
  --category bug \
  --related-files "src/memory/db_pg.py"
```

### Save a pattern

```bash
memory save \
  --title "MCP SSE requires app-level transport" \
  --what "SseServerTransport must be created at Starlette app level, not per-request" \
  --why "Transport manages connection lifecycle, per-request creates orphaned connections" \
  --impact "SSE connections now work reliably for multi-user setup" \
  --tags "mcp,sse,fastmcp,starlette" \
  --category pattern
```

### Save context

```bash
memory save \
  --title "VM deployment: instance-wu-2" \
  --what "CodeVault deployed to GCP VM instance-wu-2 (34.38.211.154)" \
  --why "Central server for multi-user memory access" \
  --impact "Both users connect via SSE on port 8420" \
  --tags "deployment,gcp,docker,infrastructure" \
  --category context
```
