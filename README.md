<p align="center">
  <img src="assets/codevault-icon.svg" width="120" height="120" alt="EchoVault" />
</p>

<h1 align="center">EchoVault</h1>

<p align="center">
  Local memory for coding agents. Your agent remembers decisions, bugs, and context across sessions — no cloud, no API keys, no cost.
</p>

<p align="center">
  <a href="#install">Install</a> · <a href="#features">Features</a> · <a href="#how-it-works">How it works</a> · <a href="#commands">Commands</a> · <a href="https://muhammadraza.me/2026/building-local-memory-for-coding-agents/">Blog post</a>
</p>

---

EchoVault gives your agent persistent memory. Every decision, bug fix, and lesson learned is saved locally and automatically surfaced in future sessions. Your agent gets better the more you use it.

### Why I built this

Coding agents forget everything between sessions. They re-discover the same patterns, repeat the same mistakes, and forget the decisions you made yesterday. I tried other tools like Supermemory and Claude Mem — both are great, but they didn't fit my use case.

Supermemory saves everything in the cloud, which was a deal breaker since I work with multiple companies as a consultant and don't want codebase decisions stored remotely. Claude Mem caused my sessions to consume too much memory, making it hard to run multiple sessions at the same time.

I built EchoVault to solve this: local memory persistence for coding agents that's simple, fast, and private.

## Features

**Works with 4 agents** — Claude Code, Cursor, Codex, OpenCode. One command sets up MCP config for your agent.

**MCP native** — Runs as an MCP server exposing `memory_save`, `memory_search`, and `memory_context` as tools. Agents call them directly — no shell hooks needed.

**Local-first** — Everything stays on your machine. Memories are stored as Markdown in `~/.memory/vault/`, readable in Obsidian or any editor. No data leaves your machine unless you opt into cloud embeddings.

**Zero idle cost** — No background processes, no daemon, no RAM overhead. The MCP server only runs when the agent starts it.

**Hybrid search** — FTS5 keyword search works out of the box. Add Ollama, OpenAI, or OpenRouter for semantic vector search.

**Secret redaction** — 3-layer redaction strips API keys, passwords, and credentials before anything hits disk. Supports explicit `<redacted>` tags, pattern detection, and custom `.memoryignore` rules.

**Cross-agent** — Memories saved by Claude Code are searchable in Cursor, Codex, and OpenCode. One vault, many agents.

**Obsidian-compatible** — Session files are valid Markdown with YAML frontmatter. Point Obsidian at `~/.memory/vault/` and browse your agent's memory visually.

## Install

```bash
pip install git+https://github.com/mraza007/codevault.git
memory init
memory setup claude-code   # or: cursor, codex, opencode
```

That's it. `memory setup` installs MCP server config automatically.

By default config is installed globally. To install for a specific project:

```bash
cd ~/my-project
memory setup claude-code --project   # writes .mcp.json in project root
memory setup opencode --project      # writes opencode.json in project root
memory setup codex --project         # writes .codex/config.toml + AGENTS.md
```

### Full bundle install (recommended for Claude Code)

`memory setup` only writes the MCP server config (one JSON entry). For Claude Code, there's a better option — `memory install` sets up the complete memory integration in one command:

```bash
cd ~/my-project
memory install claude-code --url https://your-server.com --token YOUR_TOKEN
```

#### What `memory install` creates

| File | Purpose |
|------|---------|
| `.claude/skills/memory-agent/SKILL.md` | Protocol that tells the agent **when** to load/save memories, what categories to use, and checkpoint rules. Without this, the agent doesn't know it has memory. |
| `.claude/hooks/session-start.sh` | Runs at session start. Creates a session log file (`.claude/logs/session-*.jsonl`) and injects a short reminder that memory is active. |
| `.claude/hooks/session-stop.sh` | Runs when the agent tries to stop. If meaningful work was done (>2 tool uses) but no `memory_save` was called, **blocks the stop** and asks the agent to save. On second stop attempt, allows through. This is the safety net that prevents forgotten saves. |
| `.claude/hooks/log-prompt.sh` | Logs every user prompt to the session JSONL (async, never blocks). Used by the stop hook to detect activity. |
| `.claude/hooks/log-tool-use.sh` | Logs Bash tool usage to the session JSONL. Used by the stop hook to count meaningful work. |
| `.claude/hooks/log-memory-op.sh` | Logs Memory MCP calls (save, search, context) to the session JSONL. Used by the stop hook to detect if a save already happened. |
| `.claude/hooks/on-commit.sh` | Detects successful `git commit` and nudges the agent to save a memory if the commit was meaningful. |
| `.claude/settings.local.json` | Hooks configuration — wires the 6 scripts above to Claude Code lifecycle events (SessionStart, UserPromptSubmit, PostToolUse, Stop). **Merged** with existing settings: your permissions and custom hooks are preserved. |
| `.mcp.json` | MCP server connection with your URL and Bearer token. **Merged** with existing servers: other MCP servers you have configured are preserved. |
| `.claude/.codevault-manifest.json` | Version tracking — records bundle version, content hashes of every file, and install timestamp. Used by `memory status` and `memory update`. |

#### Where does the bundle come from?

The MCP server exposes REST endpoints alongside the normal MCP transport:

- `GET /bundles` — lists available bundles (currently just `claude-code`)
- `GET /bundles/claude-code` — returns the full manifest with all file contents

When you run `memory install claude-code --url URL --token TOKEN`, the CLI fetches the bundle from the server, resolves template variables (your URL, token, project name), and writes everything to disk. This means all your projects get the **exact same version** of skills and hooks — no drift from manual copying.

#### Keeping projects in sync

```bash
memory status              # shows installed version, modified files, update availability
memory update              # re-fetches latest from server, writes updated files
memory update --check      # dry run — shows what would change without writing
memory update --force      # overwrite even if you edited hooks locally
```

`memory status` computes SHA-256 hashes of your local files and compares them to the manifest. If you edited a hook script, it shows up as "modified". `memory update` warns about conflicts and requires `--force` to overwrite your changes.

URL and token for `status`/`update` are auto-resolved from your existing `.mcp.json` — no need to pass `--url`/`--token` again after initial install.

#### Offline install

If the server is unreachable or you just want to set up hooks without connecting to a remote server:

```bash
memory install claude-code --offline
```

This uses the bundle content embedded in the Python package itself (the same files, just read from `src/memory/bundles.py` instead of fetched over HTTP). Everything is installed the same way — skills, hooks, settings — except `.mcp.json` is **not** written (no server URL to configure). You can add the MCP config separately with `memory setup claude-code --project`.

This is useful for:
- Local-only SQLite mode (no remote server at all)
- CI/CD environments where the server may not be accessible
- Testing the hook/skill setup before connecting to a real server

#### Settings merge behavior

`memory install` never overwrites your entire `settings.local.json`. It does a targeted merge:

- **`hooks`** key: bundle hooks are added/updated, identified by their command path (`.claude/hooks/*.sh`). Any hooks you added manually with different command paths are kept.
- **`permissions`** key: never touched. Your `allow`, `deny`, and `ask` rules stay exactly as they are.
- **`enableAllProjectMcpServers`**: set to `true` so the MCP server from `.mcp.json` is picked up.
- A **backup** is created at `settings.local.json.bak` before every modification.

Similarly, `.mcp.json` merge adds/updates the `memory` server entry but preserves any other servers you have configured.

### Configure embeddings (optional)

Embeddings enable semantic search. Without them, you still get fast keyword search via FTS5.

Generate a starter config:

```bash
memory config init
```

This creates `~/.memory/config.yaml` with sensible defaults:

```yaml
embedding:
  provider: ollama              # ollama | openai | openrouter
  model: nomic-embed-text

enrichment:
  provider: none                # none | ollama | openai | openrouter

context:
  semantic: auto                # auto | always | never
  topup_recent: true
```

**What each section does:**

- **`embedding`** — How memories get turned into vectors for semantic search. `ollama` runs locally, `openai` and `openrouter` call cloud APIs. `nomic-embed-text` is a good local model for Ollama.
- **`enrichment`** — Optional LLM step that enhances memories before storing (better summaries, auto-tags). Set to `none` to skip.
- **`context`** — Controls how memories are retrieved at session start. `auto` uses vector search when embeddings are available, falls back to keywords. `topup_recent` also includes recent memories so the agent has fresh context.

For cloud providers, add `api_key` under the provider section. API keys are redacted in `memory config` output.

### Configure memory location

By default, EchoVault stores data in `~/.memory`.

You can change that in two ways:

- `MEMORY_HOME=/path/to/memory` (highest priority, per-shell/per-process)
- `memory config set-home /path/to/memory` (persistent default)

Useful commands:

```bash
memory config set-home /path/to/memory
memory config clear-home
memory config
```

`memory config` now shows both `memory_home` and `memory_home_source` (`env`, `config`, or `default`).

## Usage

Once set up, your agent uses memory via MCP tools:

- **Session start** — agent calls `memory_context` to load prior decisions and context
- **During work** — agent calls `memory_search` to find relevant memories
- **Session end** — agent calls `memory_save` to persist decisions, bugs, and learnings

The MCP tool descriptions instruct agents to save and retrieve automatically. No manual prompting needed in most cases.

**Auto-save hooks (Claude Code)** — `memory install claude-code` sets up session hooks that log activity and block the agent from stopping without saving. If you prefer manual setup, see the `starter-kit/` directory.

You can also use the CLI directly:

```bash
memory save --title "Switched to JWT auth" \
  --what "Replaced session cookies with JWT" \
  --why "Needed stateless auth for API" \
  --impact "All endpoints now require Bearer token" \
  --tags "auth,jwt" --category "decision" \
  --details "Context:
Options considered:
- Keep session cookies
- Move to JWT
Decision:
Tradeoffs:
Follow-up:"

memory search "authentication"
memory details <id>
memory context --project
```

For long details, use `--details-file notes.md`. To scaffold structured details automatically, use `--details-template`.

## How it works

```
~/.memory/
├── vault/                    # Obsidian-compatible Markdown
│   └── my-project/
│       └── 2026-02-01-session.md
├── index.db                  # SQLite: FTS5 + sqlite-vec
└── config.yaml               # Embedding provider config
```

- **Markdown vault** — one file per session per project, with YAML frontmatter
- **SQLite index** — FTS5 for keywords, sqlite-vec for semantic vectors
- **Compact pointers** — search returns ~50-token summaries; full details fetched on demand
- **3-layer redaction** — explicit tags, pattern matching, and `.memoryignore` rules

## Supported agents

| Agent | Setup command | What gets installed |
|-------|-------------|-------------------|
| Claude Code | `memory install claude-code` | Full bundle: skills, hooks, settings, `.mcp.json` |
| Claude Code | `memory setup claude-code` | MCP server config only (`.mcp.json` or `~/.claude.json`) |
| Cursor | `memory setup cursor` | MCP server in `.cursor/mcp.json` |
| Codex | `memory setup codex` | MCP server in `.codex/config.toml` + `AGENTS.md` fallback |
| OpenCode | `memory setup opencode` | MCP server in `opencode.json` or `~/.config/opencode/opencode.json` |

All agents share the same memory vault at your effective `memory_home` path (default `~/.memory/`). A memory saved by Claude Code is searchable from Cursor, Codex, or OpenCode.

## Commands

### Bundle management

| Command | Description |
|---------|-------------|
| `memory install claude-code --url URL --token TOKEN` | Fetch bundle from server, install skills + hooks + settings + `.mcp.json` into current project |
| `memory install claude-code --offline` | Same as above but from local Python package — no server needed, no `.mcp.json` written |
| `memory status` | Show installed bundle version, list locally modified files, check if server has a newer version |
| `memory update` | Re-fetch bundle from server and update all managed files. Warns if you edited hooks locally |
| `memory update --check` | Dry run — show what would change without writing anything |
| `memory update --force` | Overwrite locally modified files without warning |

### Setup (MCP config only, no hooks)

| Command | Description |
|---------|-------------|
| `memory setup <agent>` | Write MCP server entry for an agent (claude-code, cursor, codex, opencode) |
| `memory uninstall <agent>` | Remove MCP server entry |

### Memory operations

| Command | Description |
|---------|-------------|
| `memory save ...` | Save a memory (`--title`, `--what` required; `--details-file`, `--details-template` supported) |
| `memory search "query"` | Hybrid FTS + semantic search (`--limit`, `--project`, `--source`, `--agent`) |
| `memory details <id>` | Full details for a memory (when search shows "Details: available") |
| `memory delete <id>` | Delete a memory by ID or prefix |
| `memory context --project` | List memories for current project (`--limit`, `--semantic`, `--fts-only`) |
| `memory sessions` | List session files (`--limit`, `--project`) |
| `memory reindex` | Rebuild vector embeddings after changing provider |

### Configuration

| Command | Description |
|---------|-------------|
| `memory init` | Create vault at effective memory home (or run PG migrations) |
| `memory config` | Show effective config (memory home, embedding provider, storage backend) |
| `memory config init` | Generate a starter `config.yaml` with defaults |
| `memory config set-home <path>` | Persist default memory location |
| `memory config clear-home` | Remove persisted memory location |
| `memory mcp` | Start the MCP server (`--transport stdio\|sse\|http`, `--port`, `--host`) |

### User management (PostgreSQL only)

| Command | Description |
|---------|-------------|
| `memory user add <name>` | Create a user, print their auth token |
| `memory user list` | List all users |

## Uninstall

```bash
memory uninstall claude-code   # or: cursor, codex, opencode
pip uninstall codevault
```

To also remove all stored memories: `rm -rf ~/.memory/`

## Blog post

[I Built Local Memory for Coding Agents Because They Keep Forgetting Everything](https://muhammadraza.me/2026/building-local-memory-for-coding-agents/)

## Privacy

Everything stays local by default. If you configure OpenAI or OpenRouter for embeddings, those API calls go to their servers. Use Ollama for fully local operation.

## License

MIT — see [LICENSE](LICENSE).
