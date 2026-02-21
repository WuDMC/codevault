# EchoVault Fork: Multi-User Remote Memory

This fork adapts [mraza007/codevault](https://github.com/mraza007/codevault) from **local-only SQLite** to **remote PostgreSQL + pgvector** with **multi-user support** and **SSE transport**.

---

## What Changed?

### ✅ Added Features

#### 1. **PostgreSQL Backend** (`src/memory/db_pg.py`)
- Full PostgreSQL + pgvector implementation
- User-scoped queries (`WHERE user_id = X`)
- Full-text search via `tsvector` + `ts_rank`
- Vector search via `pgvector` cosine similarity
- Admin methods: `create_user()`, `list_users()`, `get_user_by_token()`

#### 2. **Multi-User Auth**
- Token-based authentication (Bearer tokens)
- User isolation at database level
- Each user gets a unique token (generated with `gen_random_bytes(32)`)
- CLI commands: `memory user add <name>`, `memory user list`

#### 3. **SSE Transport** (`src/memory/mcp_server_sse.py`)
- MCP server with SSE/HTTP support (remote access)
- Backward compatible: stdio still works for local mode
- CLI: `memory mcp --transport sse --port 8420 --host 0.0.0.0`
- Auth middleware: extracts Bearer token → resolves `user_id`

#### 4. **Config System Enhancements** (`src/memory/config.py`)
- New `StorageConfig`: `backend: sqlite|postgresql`, `url: postgresql://...`
- New `AuthConfig`: `token: abc123...` (or `MEMORY_AUTH_TOKEN` env var)
- Environment variable fallbacks: `OPENAI_API_KEY`, `MEMORY_AUTH_TOKEN`

#### 5. **Hybrid Backend Support** (`src/memory/core.py`)
- `MemoryService` auto-selects backend based on `config.storage.backend`
- Factory pattern: `if backend == "postgresql": use db_pg.py, else: use db.py`
- Fully backward compatible with original SQLite mode

---

## What Stayed the Same?

✅ All original EchoVault features **preserved**:
- CLI commands: `memory save`, `memory search`, `memory context`, `memory delete`, etc.
- Structured memory format: `--what`, `--why`, `--impact`, `--tags`, `--category`, `--details`
- Secret redaction (3-layer: explicit tags, pattern detection, `.memoryignore`)
- Obsidian-compatible Markdown export (optional — now export-only, not primary storage)
- MCP tools: `memory_save`, `memory_search`, `memory_context`
- Embedding providers: OpenAI, Ollama
- Skill files for Claude Code hooks

---

## Architecture: Before vs After

### Before (Original EchoVault)
```
Laptop (local only)
┌─────────────────────┐
│ Claude Code         │
│   ↕ MCP stdio       │
│ ~/.memory/          │
│   ├── index.db      │  ← SQLite + sqlite-vec
│   └── vault/        │  ← Markdown files (primary storage)
└─────────────────────┘
```

### After (This Fork)
```
Laptop (You)                          GCP VM
┌─────────────────┐                  ┌──────────────────────┐
│ Claude Code     │                  │ memory mcp (SSE)     │
│   ↕ MCP SSE     │─── HTTPS ────→  │   port 8420          │
│ config: token=A │                  │   ↕                  │
└─────────────────┘                  │ PostgreSQL 16        │
                                     │   + pgvector         │
Laptop (Wife)                        │   user_id scoping    │
┌─────────────────┐                  │                      │
│ Claude Code     │                  │ Nginx (optional SSL) │
│   ↕ MCP SSE     │─── HTTPS ────→  │                      │
│ config: token=B │                  │                      │
└─────────────────┘                  └──────────────────────┘
```

---

## File Changes Summary

| File | Status | Description |
|------|--------|-------------|
| `src/memory/db_pg.py` | **NEW** | PostgreSQL backend with multi-user support |
| `src/memory/mcp_server_sse.py` | **NEW** | SSE transport MCP server with auth |
| `src/memory/config.py` | **MODIFIED** | Added `StorageConfig`, `AuthConfig` |
| `src/memory/core.py` | **MODIFIED** | Multi-backend factory pattern |
| `src/memory/cli.py` | **MODIFIED** | Added `memory user add/list`, `memory mcp --transport sse` |
| `pyproject.toml` | **MODIFIED** | Added `psycopg2-binary`, `pgvector`, `starlette`, `uvicorn` |
| `config.yaml.example` | **NEW** | Sample config for PostgreSQL setup |
| `SETUP_MULTIUSER.md` | **NEW** | Complete setup guide for server + clients |
| All other files | **UNCHANGED** | Original EchoVault code preserved |

---

## Usage Examples

### Local Mode (SQLite, Original Behavior)
```bash
# config.yaml (or omit for defaults)
storage:
  backend: sqlite

# CLI works as before
memory save --what "Fixed auth bug" --category bug
memory search "authentication"
memory mcp  # stdio transport
```

### Remote Mode (PostgreSQL, Multi-User)
```bash
# Server setup (GCP VM)
# config.yaml
storage:
  backend: postgresql
  url: postgresql://user:pass@localhost:5432/memory

# Create users
memory user add sasha   # → Token: abc123...
memory user add wife    # → Token: xyz789...

# Run MCP server
memory mcp --transport sse --port 8420 --host 0.0.0.0
```

```bash
# Client setup (Laptop)
# config.yaml
storage:
  backend: postgresql
  url: postgresql://user:pass@VM_IP:5432/memory
auth:
  token: abc123...  # Your personal token

# Claude Code config (~/.claude/settings.json)
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://VM_IP:8420/sse",
      "headers": {
        "Authorization": "Bearer abc123..."
      }
    }
  }
}

# Use as normal
memory search "bug fixes"
# Claude Code calls memory_save, memory_search, memory_context via SSE
```

---

## Database Schema (PostgreSQL)

### Users Table
```sql
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    token       VARCHAR(64) NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### Memories Table
```sql
CREATE TABLE memories (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    memory_id   VARCHAR(36) NOT NULL,
    title       TEXT NOT NULL,
    what        TEXT NOT NULL,
    why         TEXT,
    impact      TEXT,
    tags        TEXT[] DEFAULT '{}',
    category    VARCHAR(50) DEFAULT 'note',
    project     VARCHAR(255),
    embedding   VECTOR(1536),  -- pgvector
    fts         TSVECTOR,       -- full-text search
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, memory_id)
);
```

### Indexes
- `idx_memories_user` (user_id, created_at DESC)
- `idx_memories_embedding` (HNSW vector index)
- `idx_memories_fts` (GIN index for full-text)

---

## Migration Path

### From Original EchoVault to This Fork

**Step 1: Install fork**
```bash
pip uninstall codevault
pip install git+https://github.com/YOUR_USERNAME/codevault.git
```

**Step 2: Keep using local SQLite (no changes needed)**
```bash
# Your existing ~/.memory/config.yaml works as-is
# OR omit config.yaml entirely — defaults to SQLite
```

**Step 3 (Optional): Migrate to PostgreSQL**
```bash
# 1. Setup PostgreSQL on VM (see SETUP_MULTIUSER.md)
# 2. Update config.yaml:
storage:
  backend: postgresql
  url: postgresql://...
auth:
  token: YOUR_TOKEN

# 3. Export/import (TODO: implement migration commands)
```

---

## Dependencies Added

```toml
dependencies = [
    # ... existing codevault deps ...
    "psycopg2-binary>=2.9.9",  # PostgreSQL driver
    "pgvector>=0.3.0",          # pgvector Python support
    "starlette>=0.37.0",        # SSE transport
    "uvicorn>=0.29.0",          # ASGI server
]
```

---

## Design Decisions

### Why PostgreSQL Instead of SQLite?
- **Multi-user support**: SQLite doesn't support concurrent writes well
- **Remote access**: PostgreSQL can run on a separate server
- **pgvector**: Native vector similarity search (better than sqlite-vec for multi-user)
- **ACID guarantees**: Strong consistency for concurrent access

### Why Keep SQLite Support?
- **Backward compatibility**: Existing EchoVault users can upgrade without breaking changes
- **Local mode**: Some users prefer fully local setup (no server needed)
- **Simplicity**: SQLite is easier for single-user, local-only use cases

### Why SSE Instead of stdio?
- **Remote access**: stdio only works for local processes
- **HTTP-based**: Works over network, firewall-friendly
- **Token auth**: Easy to secure with Bearer tokens
- **Stateful**: SSE maintains persistent connection (good for MCP)

### Why Not gRPC or WebSocket?
- **MCP support**: MCP spec defines SSE as standard remote transport
- **Simplicity**: HTTP/SSE is simpler than gRPC (no protobuf)
- **Compatibility**: SSE works with existing HTTP infrastructure (Nginx, Let's Encrypt)

---

## Testing Checklist

- [x] SQLite backend still works (backward compatibility)
- [ ] PostgreSQL backend: save, search, delete
- [ ] Multi-user isolation (user A can't see user B's memories)
- [ ] Token auth (invalid token → 401)
- [ ] SSE transport (remote MCP connection)
- [ ] Embedding generation (OpenAI + Ollama)
- [ ] FTS search (tsvector)
- [ ] Vector search (pgvector cosine similarity)
- [ ] CLI commands (`memory user add/list`)
- [ ] Claude Code integration (SSE config)

---

## Known Issues / TODOs

- [ ] Migration tool: `memory export/import` for SQLite → PostgreSQL
- [ ] Token rotation: `memory user rotate-token <name>`
- [ ] User deletion: `memory user delete <id>`
- [ ] Audit logging: track who saved what
- [ ] Rate limiting for API abuse prevention
- [ ] Batch embedding updates (performance optimization)
- [ ] Health check endpoint: `/health`

---

## Credits

- **Original EchoVault**: [mraza007/codevault](https://github.com/mraza007/codevault)
- **This fork**: Adapted for multi-user PostgreSQL + SSE by @denismironov

---

## License

Same as original EchoVault (check LICENSE file).

---

## Getting Started

See [SETUP_MULTIUSER.md](./SETUP_MULTIUSER.md) for complete setup instructions.
