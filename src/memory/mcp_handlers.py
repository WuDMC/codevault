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
- Follow-up

Set `agent` to 'interactive' for human-driven sessions or 'autonomous:<role>' for autonomous agents (e.g. 'autonomous:architect')."""

SEARCH_DESCRIPTION = """Search memories by keyword and semantic similarity. Use this to find specific memories across all projects and history. Supports filtering by project, source, and agent role. Use when you need something beyond the recent context — e.g. a memory from another project, an old decision, or a specific topic."""

CONTEXT_DESCRIPTION = """Load recent memories and active epics for the current project. You MUST call this at session start before doing any work. Returns full content (what, why, impact) so you have all prior decisions, and active epics with their checklists.

If the response contains `epics`, identify which epic to work on:
- If the user specified a ticket → use memory_epic_find to get it
- If only 1 active epic → use it
- If multiple → ask the user which one
- For adhoc work → use the Backlog epic

If a memory has has_details=true, call memory_details to get the extended body. Use memory_search when you need to find something outside this project or beyond the recent limit."""

DETAILS_DESCRIPTION = """Get extended details for a specific memory by ID. Only call this when has_details is true in a result from memory_context or memory_search. If has_details is false, do NOT call this — the memory has no extended details."""

EPIC_ADD_DESCRIPTION = """Create a new epic (multi-session work item). Epics group related work under a ticket or title. Use when starting significant work: a feature, a refactor, a bug fix that spans multiple steps. For adhoc tasks, use the auto-created Backlog epic instead."""

EPIC_GET_DESCRIPTION = """Get an epic by ID, including its full Markdown checklist. Use this to see current progress on an epic you're working on."""

EPIC_FIND_DESCRIPTION = """Find an epic by ticket name (e.g. 'AUTH-123'). Returns the epic if found, null if not. Use at session start when the user tells you which ticket to work on."""

EPIC_LIST_DESCRIPTION = """List epics for a project. Returns active epics by default. Use status='all' to include done/cancelled. Primarily for architects and users to see the full picture."""

EPIC_UPDATE_DESCRIPTION = """Update an epic's status, title, or checklist. Use this to:
- Update the Markdown checklist as you complete steps: description="- [x] done step\\n- [ ] next step"
- Mark an epic as done when all work is complete: status="done"
- Cancel an epic: status="cancelled"
Always update the checklist before ending a session if you made progress."""

PROJECT_REGISTER_DESCRIPTION = """Register a new project. Projects must be registered before memories can be saved to them. The project name is auto-detected from the current working directory, but must match a registered project. Use this when memory_save tells you the project is not registered."""

PROJECT_LIST_DESCRIPTION = """List all registered projects for the current user."""


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


def normalize_agent(agent: Optional[str]) -> str:
    """Normalize agent field to structured format.

    'interactive' for human-driven sessions, 'autonomous:<role>' for agents.
    """
    if not agent or agent.lower() in ("interactive", "human", "cli"):
        return "interactive"
    if agent.startswith("autonomous:"):
        return agent
    return f"autonomous:{agent}"


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
    epic_id: Optional[int] = None,
) -> str:
    """Handle memory_save tool call. Returns JSON string."""
    project = project or os.path.basename(os.getcwd())
    agent = normalize_agent(agent)

    # Check project registration (PG only)
    if not service.project_exists(project):
        registered = service.list_projects()
        project_names = [p["name"] for p in registered]
        return json.dumps({
            "error": "project_not_registered",
            "project": project,
            "registered_projects": project_names,
            "instructions": "Use memory_project_register to register this project, or pass a different project name from the registered list.",
        })

    if category and category not in VALID_CATEGORIES:
        category = "context"

    # If epic_id provided, auto-add ticket as tag
    final_tags = list(tags or [])
    if epic_id:
        try:
            epic = service.get_epic(epic_id)
            if epic and epic.get("ticket") and epic["ticket"] != "_backlog":
                ticket_tag = epic["ticket"]
                if ticket_tag not in final_tags:
                    final_tags.append(ticket_tag)
        except Exception:
            pass

    raw = RawMemoryInput(
        title=title[:60],
        what=what,
        why=why,
        impact=impact,
        tags=final_tags,
        category=category,
        related_files=related_files or [],
        details=details,
        source=source,
        agent=agent,
        epic_id=epic_id,
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
            "what": r.get("what", ""),
            "why": r.get("why"),
            "impact": r.get("impact"),
            "category": r.get("category", ""),
            "tags": tags_list,
            "date": date_display,
            "has_details": bool(r.get("has_details")),
        })

    # Ensure Backlog epic exists for this project
    try:
        service.ensure_backlog_epic(project)
    except Exception:
        pass  # Non-PG backend or user_id not set

    # Fetch active epics for the project
    epics = service.list_epics(project, status="active")
    epic_items = []
    for e in epics:
        desc = e.get("description", "")
        # Count checklist progress
        total_items = desc.count("- [")
        done_items = desc.count("- [x]")
        epic_items.append({
            "id": e["id"],
            "ticket": e.get("ticket"),
            "title": e["title"],
            "status": e["status"],
            "checklist_progress": f"{done_items}/{total_items}" if total_items > 0 else "no checklist",
            "description": desc[:500] if desc else "",
        })

    response = {
        "total": total,
        "showing": len(memories),
        "memories": memories,
        "epics": epic_items,
        "message": "IMPORTANT: Identify your epic before starting work. Save memories with epic_id. Update epic checklist before session ends.",
    }

    if epic_items:
        non_backlog = [e for e in epic_items if e.get("ticket") != "_backlog"]
        if non_backlog:
            response["epic_instructions"] = (
                f"Active epics: {', '.join(e['title'] + ' (#' + str(e['id']) + ')' for e in non_backlog)}. "
                "Ask the user which epic to work on, or use memory_epic_find(ticket=...) if they specify a ticket."
            )

    return json.dumps(response)


def handle_memory_details(
    service: MemoryService,
    memory_id: str,
) -> str:
    """Handle memory_details tool call. Returns JSON string."""
    detail = service.get_details(memory_id)
    if not detail:
        return json.dumps({"error": f"No details found for memory {memory_id}"})
    return json.dumps({"memory_id": detail.memory_id, "body": detail.body})


def handle_memory_epic_add(
    service: MemoryService,
    project: str,
    title: str,
    ticket: Optional[str] = None,
    description: str = "",
) -> str:
    """Handle memory_epic_add tool call."""
    project = project or os.path.basename(os.getcwd())
    result = service.add_epic(project, title, ticket, description)
    return json.dumps(result)


def handle_memory_epic_get(
    service: MemoryService,
    epic_id: int,
) -> str:
    """Handle memory_epic_get tool call."""
    result = service.get_epic(epic_id)
    if result is None:
        return json.dumps({"error": f"Epic {epic_id} not found"})
    return json.dumps(result)


def handle_memory_epic_find(
    service: MemoryService,
    ticket: str,
    project: Optional[str] = None,
) -> str:
    """Handle memory_epic_find tool call."""
    result = service.find_epic(ticket, project)
    if result is None:
        return json.dumps({"error": f"No epic found for ticket '{ticket}'"})
    return json.dumps(result)


def handle_memory_epic_list(
    service: MemoryService,
    project: Optional[str] = None,
    status: Optional[str] = "active",
) -> str:
    """Handle memory_epic_list tool call."""
    project = project or os.path.basename(os.getcwd())
    epics = service.list_epics(project, status)
    return json.dumps({"project": project, "epics": epics, "total": len(epics)})


def handle_memory_epic_update(
    service: MemoryService,
    epic_id: int,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    ticket: Optional[str] = None,
) -> str:
    """Handle memory_epic_update tool call."""
    result = service.update_epic(epic_id, status, title, description, ticket)
    if result is None:
        return json.dumps({"error": f"Epic {epic_id} not found"})
    return json.dumps(result)


def handle_memory_project_register(
    service: MemoryService,
    name: str,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Handle memory_project_register tool call."""
    result = service.register_project(name, display_name, description)
    return json.dumps(result)


def handle_memory_project_list(service: MemoryService) -> str:
    """Handle memory_project_list tool call."""
    projects = service.list_projects()
    return json.dumps({"projects": projects})


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
                        "project": {"type": "string", "description": "Project name. Auto-detected from cwd if omitted. Must be registered."},
                        "source": {"type": "string", "description": "Client/IDE that saved this: claude-code, cursor, codex."},
                        "agent": {
                            "type": "string",
                            "description": (
                                "Agent type. Use 'interactive' for human-driven sessions "
                                "(Claude Code interactive, CLI). Use 'autonomous:<role>' for "
                                "autonomous agents (e.g. 'autonomous:architect', 'autonomous:reviewer'). "
                                "Default: 'interactive'."
                            ),
                        },
                        "epic_id": {"type": "integer", "description": "Epic ID to link this memory to. Auto-adds epic's ticket as tag."},
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
            Tool(
                name="memory_epic_add",
                description=EPIC_ADD_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project name. Auto-detected from cwd if omitted."},
                        "title": {"type": "string", "description": "Epic title."},
                        "ticket": {"type": "string", "description": "Ticket reference (e.g. 'AUTH-123'). Optional."},
                        "description": {"type": "string", "description": "Markdown checklist of steps. e.g. '- [ ] step 1\\n- [ ] step 2'"},
                    },
                    "required": ["title"],
                },
            ),
            Tool(
                name="memory_epic_get",
                description=EPIC_GET_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "epic_id": {"type": "integer", "description": "Epic ID."},
                    },
                    "required": ["epic_id"],
                },
            ),
            Tool(
                name="memory_epic_find",
                description=EPIC_FIND_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string", "description": "Ticket name to search for (e.g. 'AUTH-123')."},
                        "project": {"type": "string", "description": "Filter to project."},
                    },
                    "required": ["ticket"],
                },
            ),
            Tool(
                name="memory_epic_list",
                description=EPIC_LIST_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project name. Auto-detected from cwd if omitted."},
                        "status": {"type": "string", "enum": ["active", "done", "cancelled", "all"], "default": "active", "description": "Filter by status."},
                    },
                },
            ),
            Tool(
                name="memory_epic_update",
                description=EPIC_UPDATE_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "epic_id": {"type": "integer", "description": "Epic ID."},
                        "status": {"type": "string", "enum": ["active", "done", "cancelled"], "description": "New status."},
                        "title": {"type": "string", "description": "Updated title."},
                        "description": {"type": "string", "description": "Full Markdown checklist (replaces existing)."},
                        "ticket": {"type": "string", "description": "Updated ticket reference."},
                    },
                    "required": ["epic_id"],
                },
            ),
            Tool(
                name="memory_project_register",
                description=PROJECT_REGISTER_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Project name (slug). Auto-detected from cwd if omitted."},
                        "display_name": {"type": "string", "description": "Human-readable project name."},
                        "description": {"type": "string", "description": "Project description."},
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="memory_project_list",
                description=PROJECT_LIST_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {},
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
            elif name == "memory_epic_add":
                result = handle_memory_epic_add(service, **arguments)
            elif name == "memory_epic_get":
                result = handle_memory_epic_get(service, **arguments)
            elif name == "memory_epic_find":
                result = handle_memory_epic_find(service, **arguments)
            elif name == "memory_epic_list":
                result = handle_memory_epic_list(service, **arguments)
            elif name == "memory_epic_update":
                result = handle_memory_epic_update(service, **arguments)
            elif name == "memory_project_register":
                result = handle_memory_project_register(service, **arguments)
            elif name == "memory_project_list":
                result = handle_memory_project_list(service)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            print(f"[ERROR] {name}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            result = json.dumps({"error": str(e)})

        return [TextContent(type="text", text=result)]

    return server
