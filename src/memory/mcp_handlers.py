"""Shared MCP tool handlers, descriptions, and server factory.

Both stdio and SSE transports import from this module to avoid duplication.
"""

import json
import os
from datetime import datetime
from typing import Optional

from mcp.server import Server
from mcp.types import TextContent, Tool

from memory.core import MemoryService
from memory.models import RawMemoryInput

VALID_CATEGORIES = ("decision", "bug", "pattern", "learning", "context")

SAVE_DESCRIPTION = """Save a memory for future sessions. You MUST call this before ending any session where you made changes, fixed bugs, made decisions, or learned something. This is not optional — failing to save means the next session starts from zero.

Save when you:
- Made an architectural or design decision (chose X over Y)
- Fixed a bug (include root cause and solution)
- Discovered a non-obvious pattern or gotcha
- Learned something about the codebase not obvious from code
- Set up infrastructure, tooling, or configuration
- The user corrected you or clarified a requirement

Do NOT save: trivial changes (typos, formatting), info obvious from reading the code, or duplicates of existing memories. Write for a future agent with zero context.

When filling `details`, prefer this structure:
- Context
- Options considered
- Decision
- Tradeoffs
- Follow-up"""

SEARCH_DESCRIPTION = """Search memories using keyword and semantic search. Returns matching memories ranked by relevance. You MUST call this at session start before doing any work, and whenever the user's request relates to a topic that may have prior context."""

CONTEXT_DESCRIPTION = """Get memory context for the current project. You MUST call this at session start to load prior decisions, bugs, and context. Do not skip this step — prior sessions contain decisions and context that directly affect your current task.

After getting context, call memory_search with relevant keywords to get full content (what, why, impact) for memories related to your current task. Context only returns titles and metadata — search returns the actual content."""

DETAILS_DESCRIPTION = """Get full details for a specific memory by ID. Only call this if has_details is true for a memory returned by memory_search or memory_context. If has_details is false or missing, do NOT call this — the memory has no extended details."""


def _normalize_tags(tags_raw) -> list[str]:
    """Normalize tags from either JSON string (SQLite) or list (PG)."""
    if isinstance(tags_raw, list):
        return tags_raw
    if isinstance(tags_raw, str):
        try:
            return json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def handle_memory_save(
    service: MemoryService,
    title: str,
    what: str,
    why: Optional[str] = None,
    impact: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category: Optional[str] = None,
    related_files: Optional[list[str]] = None,
    details: Optional[str] = None,
    project: Optional[str] = None,
    source: Optional[str] = None,
    agent: Optional[str] = None,
) -> str:
    """Handle memory_save tool call. Returns JSON string."""
    project = project or os.path.basename(os.getcwd())

    if category and category not in VALID_CATEGORIES:
        category = "context"

    raw = RawMemoryInput(
        title=title[:60],
        what=what,
        why=why,
        impact=impact,
        tags=tags or [],
        category=category,
        related_files=related_files or [],
        details=details,
        source=source,
        agent=agent,
    )

    result = service.save(raw, project=project)
    return json.dumps(result)


def handle_memory_search(
    service: MemoryService,
    query: str,
    limit: int = 5,
    project: Optional[str] = None,
    source: Optional[str] = None,
    agent: Optional[str] = None,
) -> str:
    """Handle memory_search tool call. Returns JSON string."""
    results = service.search(query, limit=limit, project=project, source=source, agent=agent)

    clean = []
    for r in results:
        tags_list = _normalize_tags(r.get("tags", "[]"))
        created_at = str(r.get("created_at", ""))[:10]

        clean.append({
            "id": r["id"] if "id" in r else r.get("memory_id"),
            "title": r["title"],
            "what": r["what"],
            "why": r.get("why"),
            "impact": r.get("impact"),
            "category": r.get("category"),
            "tags": tags_list,
            "project": r.get("project"),
            "created_at": created_at,
            "score": round(r.get("score", 0), 2),
            "has_details": bool(r.get("has_details")),
        })
    return json.dumps(clean)


def handle_memory_context(
    service: MemoryService,
    project: Optional[str] = None,
    limit: int = 10,
    source: Optional[str] = None,
    agent: Optional[str] = None,
) -> str:
    """Handle memory_context tool call. Returns JSON string."""
    project = project or os.path.basename(os.getcwd())

    results, total = service.get_context(
        limit=limit,
        project=project,
        source=source,
        agent=agent,
        semantic_mode="never",
    )

    memories = []
    for r in results:
        tags_list = _normalize_tags(r.get("tags", "[]"))
        created_at = str(r.get("created_at", ""))[:10]

        try:
            dt = datetime.fromisoformat(created_at)
            date_display = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_display = created_at

        memories.append({
            "id": r["id"],
            "title": r.get("title", "Untitled"),
            "category": r.get("category", ""),
            "tags": tags_list,
            "date": date_display,
            "has_details": bool(r.get("has_details")),
        })

    return json.dumps({
        "total": total,
        "showing": len(memories),
        "memories": memories,
        "message": "Use memory_search for specific topics. IMPORTANT: You MUST call memory_save before this session ends if you make any changes, decisions, or discoveries.",
    })


def handle_memory_details(
    service: MemoryService,
    memory_id: str,
) -> str:
    """Handle memory_details tool call. Returns JSON string."""
    detail = service.get_details(memory_id)
    if not detail:
        return json.dumps({"error": f"No details found for memory {memory_id}"})
    return json.dumps({"memory_id": detail.memory_id, "body": detail.body})


def create_mcp_server(service: MemoryService) -> Server:
    """Create and configure the MCP server with memory tools.

    Args:
        service: MemoryService instance

    Returns:
        Configured MCP Server
    """
    server = Server("codevault")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="memory_save",
                description=SAVE_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title, max 60 chars."},
                        "what": {"type": "string", "description": "1-2 sentences. The essence a future agent needs."},
                        "why": {"type": "string", "description": "Reasoning behind the decision or fix."},
                        "impact": {"type": "string", "description": "What changed as a result."},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Relevant tags."},
                        "category": {
                            "type": "string",
                            "enum": list(VALID_CATEGORIES),
                            "description": "decision: chose X over Y. bug: fixed a problem. pattern: reusable gotcha. learning: non-obvious discovery. context: project setup/architecture.",
                        },
                        "related_files": {"type": "array", "items": {"type": "string"}, "description": "File paths involved."},
                        "details": {
                            "type": "string",
                            "description": (
                                "Full context for a future agent with zero context. "
                                "Prefer: Context, Options considered, Decision, Tradeoffs, Follow-up."
                            ),
                        },
                        "project": {"type": "string", "description": "Project name. Auto-detected from cwd if omitted."},
                        "source": {"type": "string", "description": "Client/IDE that saved this: claude-code, cursor, codex."},
                        "agent": {"type": "string", "description": "Agent role: architect, developer, reviewer, orchestrator, etc."},
                    },
                    "required": ["title", "what"],
                },
            ),
            Tool(
                name="memory_search",
                description=SEARCH_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search terms"},
                        "limit": {"type": "integer", "default": 5, "description": "Max results"},
                        "project": {"type": "string", "description": "Filter to project."},
                        "source": {"type": "string", "description": "Filter by client/IDE."},
                        "agent": {"type": "string", "description": "Filter by agent role."},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memory_context",
                description=CONTEXT_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project name. Auto-detected from cwd if omitted."},
                        "limit": {"type": "integer", "default": 10, "description": "Max memories"},
                        "source": {"type": "string", "description": "Filter by client/IDE."},
                        "agent": {"type": "string", "description": "Filter by agent role."},
                    },
                },
            ),
            Tool(
                name="memory_details",
                description=DETAILS_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID (full UUID or prefix, at least 8 chars)."},
                    },
                    "required": ["memory_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        import sys
        import traceback

        try:
            if name == "memory_save":
                result = handle_memory_save(service, **arguments)
            elif name == "memory_search":
                result = handle_memory_search(service, **arguments)
            elif name == "memory_context":
                result = handle_memory_context(service, **arguments)
            elif name == "memory_details":
                result = handle_memory_details(service, **arguments)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            print(f"[ERROR] {name}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            result = json.dumps({"error": str(e)})

        return [TextContent(type="text", text=result)]

    return server
