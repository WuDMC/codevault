# Memory Agent Starter Kit

> **Note:** This starter kit is superseded by `memory install claude-code`, which fetches the canonical skill bundle from the MCP server and installs everything automatically. Use `memory install claude-code --url URL --token TOKEN` instead of manual copying. See the [README](../README.md) for details.

Universal hooks, skills, and settings for integrating CodeVault Memory MCP into any Claude Code project.

## What's Included

```
hooks/
  session-start.sh     # Creates session log, injects reminder at start
  session-stop.sh      # Blocks stop if meaningful work wasn't saved
  log-prompt.sh        # Logs user prompts to session JSONL
  log-tool-use.sh      # Logs Bash tool usage
  log-memory-op.sh     # Logs Memory MCP operations
  on-commit.sh         # Reminds agent to save after git commit

skills/memory-agent/
  SKILL.md             # Universal memory protocol (MCP-based)

settings-template.json # Claude Code settings with all hooks pre-configured
claudemd-snippet.md    # Memory section to paste into your CLAUDE.md
```

## Setup (5 minutes)

### 1. Copy hooks and skill

```bash
cp -r starter-kit/hooks/ /path/to/your-project/.claude/hooks/
cp -r starter-kit/skills/ /path/to/your-project/.claude/skills/
chmod +x /path/to/your-project/.claude/hooks/*.sh
```

### 2. Configure settings

Copy and adapt the settings template:

```bash
cp starter-kit/settings-template.json /path/to/your-project/.claude/settings.local.json
```

Then edit `.claude/settings.local.json`:
- Add project-specific permissions to `allow` and `ask` arrays
- Add your MCP servers to `enabledMcpjsonServers` if needed

### 3. Setup Memory MCP in `.mcp.json`

Create `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://YOUR_MEMORY_SERVER/sse",
        "--header", "Authorization: Bearer YOUR_TOKEN",
        "--transport", "sse-only"
      ]
    }
  }
}
```

For local stdio mode (no server):
```json
{
  "mcpServers": {
    "memory": {
      "command": "memory",
      "args": ["mcp"]
    }
  }
}
```

### 4. Update your CLAUDE.md

Paste the contents of `claudemd-snippet.md` into your project's `CLAUDE.md`.

### 5. Update .gitignore

Add these lines to your `.gitignore`:

```
.claude/logs/
.claude/settings.local.json
```

## How It Works

### Logging (automatic, every action)

Every user prompt and tool use is logged to `.claude/logs/session-{ID}.jsonl`. These are local files used by the stop hook to detect unsaved work.

### Memory saves (agent decides)

The SKILL.md instructs the agent when to save:
- After decisions, bug fixes, pattern discoveries
- At natural checkpoints (commits, tests, deploys)
- Before session end

### Stop hook safety net (automatic)

If the agent did >2 tool uses but never called `memory_save`, the stop hook blocks the session and asks the agent to save. On the second stop attempt, it allows through.

### Commit reminder (automatic)

When a `git commit` succeeds, `on-commit.sh` nudges the agent to save a memory if the change was meaningful.

## Customization

### Add project-specific checkpoints

Edit `.claude/skills/memory-agent/SKILL.md` and fill in the `PROJECT-SPECIFIC CHECKPOINTS` section with your build/test/deploy commands.

### Add project-specific permissions

Edit `.claude/settings.local.json` and add your CLI commands:

```json
"allow": [
  "Bash(npm run build:*)",
  "Bash(npm test:*)",
  "Bash(pytest:*)"
]
```

### Add more MCP servers

Add to `.mcp.json` alongside the memory server:

```json
{
  "mcpServers": {
    "memory": { ... },
    "your-other-server": { ... }
  }
}
```

## Requirements

- `jq` (for hook scripts): `brew install jq` or `apt-get install jq`
- Memory MCP server (remote or local `memory mcp`)
- Claude Code with hooks support
