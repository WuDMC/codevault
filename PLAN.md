# Plan: Add `agent` field for multi-agent support

## Goal

Add a new `agent` field (separate from existing `source`) to support filtering memories by agent role (architect, developer, reviewer, orchestrator, etc.).

Isolation hierarchy:
```
user_id (den / maryna)                    ← already works
  └── project (codevault / geo-roulette)  ← already works
       └── agent (architect / developer)  ← NEW
```

`source` stays as-is (identifies client: claude-code, cursor, codex).
`agent` is a new independent field (identifies role: architect, developer, reviewer).

---

## Changes by file

### 1. `src/memory/models.py`
- Add `agent: Optional[str] = None` to `RawMemoryInput`
- Add `agent: Optional[str]` to `Memory`
- Add `agent: Optional[str]` to `SearchResult`
- Update `Memory.from_raw()` to copy `agent` from raw input

### 2. `src/memory/db.py` (SQLite)

**Schema:**
- Add `agent TEXT` column to `CREATE TABLE memories`
- Migration: `ALTER TABLE memories ADD COLUMN agent TEXT` for existing DBs (same pattern as `updated_count` migration on line 107-111)

**FTS5:**
- SQLite FTS5 virtual tables can't be ALTERed. Add migration that:
  1. Drops old FTS table + triggers
  2. Recreates FTS5 with `agent` column included
  3. Recreates INSERT/UPDATE triggers with `agent`
  4. Rebuilds FTS content from memories table
- Gate this behind column-existence check (only run once)

**Methods — add `agent` parameter to:**
- `insert_memory()` — include `mem.agent` in INSERT
- `fts_search(agent=None)` — add `WHERE m.agent = ?` filter
- `vector_search(agent=None)` — add post-filter by agent
- `list_recent(agent=None)` — add `WHERE m.agent = ?` filter
- `count_memories(agent=None)` — add `WHERE agent = ?` filter

### 3. `src/memory/db_pg.py` (PostgreSQL)

**Schema:**
- Add `agent TEXT` to `CREATE TABLE memories`
- Migration: `ALTER TABLE memories ADD COLUMN agent TEXT` for existing DBs (check information_schema.columns, same pattern as fts column migration)
- Add index: `CREATE INDEX idx_memories_agent ON memories (user_id, agent)`

**Methods — add `agent` parameter to:**
- `insert_memory()` — include `mem.agent` in INSERT
- `fts_search(agent=None)` — add `WHERE m.agent = %s` filter
- `vector_search(agent=None)` — add `WHERE m.agent = %s` filter
- `list_recent(agent=None)` — add `WHERE m.agent = %s` filter
- `count_memories(agent=None)` — add `WHERE agent = %s` filter

### 4. `src/memory/search.py`
- Add `agent: Optional[str] = None` to `MemoryDBLike` protocol methods
- Add `agent` parameter to `tiered_search()` — pass to `db.fts_search()` and `db.vector_search()`
- Add `agent` parameter to `hybrid_search()` — pass to `db.fts_search()` and `db.vector_search()`

### 5. `src/memory/core.py`
- `save()` — `agent` already flows via `RawMemoryInput.agent` → `Memory.agent` → `db.insert_memory()` (no change needed except model update)
- `search(agent=None)` — pass to `tiered_search()`/`hybrid_search()`
- `get_context(agent=None)` — pass to `count_memories()`, `search()`, `list_recent()`

### 6. `src/memory/mcp_handlers.py` — **key file**

Add `agent` AND `source` to all 4 MCP tools:

**memory_save:**
- Add `agent` param: `{"type": "string", "description": "Agent role: architect, developer, reviewer, orchestrator, etc."}`
- Add `source` param: `{"type": "string", "description": "Client/IDE: claude-code, cursor, codex."}`
- Pass both to `handle_memory_save()`

**memory_search:**
- Add `agent` param for filtering
- Add `source` param for filtering
- Pass both to `handle_memory_search()`

**memory_context:**
- Add `agent` param for filtering
- Add `source` param for filtering
- Pass both to `handle_memory_context()`

**memory_details:**
- No change needed (fetches by ID, no filtering)

### 7. `src/memory/cli.py`
- `save` command: add `--agent` option
- `search` command: add `--agent` option
- `context` command: add `--agent` option

### 8. `src/memory/markdown.py`
- `render_section()`: add `**Agent:** {mem.agent}` line (like source on line 31-32)

### 9. Tests
- Add `test_filter_by_agent` in test_db.py (mirror test_filter_by_source)
- Add agent filter tests in test_cli.py
- Verify existing tests still pass (agent=None everywhere = backward compatible)

### 10. `USAGE_GUIDE.md`
- Add "Multi-Agent Workflow" section with examples
- Explain agent vs source distinction
- Show per-agent save/search patterns

---

## Migration strategy

**SQLite (existing local DBs):**
1. `ALTER TABLE memories ADD COLUMN agent TEXT` — nullable, backward compatible
2. Drop + recreate FTS5 table with agent column
3. Rebuild FTS content: `INSERT INTO memories_fts(memories_fts) VALUES('rebuild')`
4. Recreate triggers with agent column

**PostgreSQL (running on VM):**
1. `ALTER TABLE memories ADD COLUMN agent TEXT` — nullable, backward compatible
2. `CREATE INDEX idx_memories_agent ON memories (user_id, agent)` — for efficient filtering
3. No FTS change needed (tsvector doesn't include source/agent — they're filtered via WHERE)

**Docker:**
- Rebuild container after code change: `docker-compose up -d --build`
- PG migration runs automatically via `_create_schema()` column-existence check

---

## Execution order

1. models.py (add field to dataclasses)
2. db.py (SQLite schema + migration + methods)
3. db_pg.py (PG schema + migration + methods)
4. search.py (protocol + search functions)
5. core.py (service methods)
6. mcp_handlers.py (expose agent + source in MCP tools)
7. cli.py (add --agent options)
8. markdown.py (render agent in output)
9. Tests
10. USAGE_GUIDE.md update
11. Docker rebuild + deploy
