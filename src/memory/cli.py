"""CLI commands for the memory system.

This module provides the command-line interface for managing memories.
All commands use the MemoryService for business logic.
"""

import os
from dataclasses import asdict

import yaml

import click

from memory.config import (
    clear_persisted_memory_home,
    get_memory_home,
    load_config,
    resolve_memory_home,
    set_persisted_memory_home,
)
from memory.core import MemoryService
from memory.models import RawMemoryInput

DETAILS_TEMPLATE = """\
Context:

Options considered:
- Option A:
- Option B:

Decision:

Tradeoffs:

Follow-up:
"""


def _redact_api_keys(data: dict) -> dict:
    for section in ("embedding",):
        config = data.get(section)
        if isinstance(config, dict) and config.get("api_key"):
            config["api_key"] = "<redacted>"
    return data


@click.group()
def main():
    """Memory — local memory for coding agents."""
    pass


@main.command()
def init():
    """Initialize the memory vault."""
    home = get_memory_home()
    vault_dir = os.path.join(home, "vault")
    os.makedirs(vault_dir, exist_ok=True)
    click.echo(f"Memory vault initialized at {home}")


@main.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """Show or manage configuration."""
    if ctx.invoked_subcommand is None:
        home, source = resolve_memory_home()
        cfg = load_config(os.path.join(home, "config.yaml"))
        data = _redact_api_keys(asdict(cfg))
        data["memory_home"] = home
        data["memory_home_source"] = source
        click.echo(yaml.safe_dump(data, sort_keys=False))


@config.command("set-home")
@click.argument("path")
def config_set_home(path):
    """Persist memory home location (used when MEMORY_HOME is unset)."""
    resolved = set_persisted_memory_home(path)
    os.makedirs(resolved, exist_ok=True)
    os.makedirs(os.path.join(resolved, "vault"), exist_ok=True)
    click.echo(f"Persisted memory home: {resolved}")
    click.echo("Override anytime with MEMORY_HOME.")


@config.command("clear-home")
def config_clear_home():
    """Remove persisted memory home location from global config."""
    changed = clear_persisted_memory_home()
    if changed:
        click.echo("Cleared persisted memory home setting.")
    else:
        click.echo("No persisted memory home setting was found.")


_CONFIG_TEMPLATE = """\
# EchoVault configuration
# Docs: https://github.com/mraza007/codevault#configure-embeddings-optional

# Embedding provider for semantic search.
# Without this, keyword search (FTS5) still works.
embedding:
  provider: ollama              # ollama | openai
  model: nomic-embed-text
  # api_key: sk-...            # required for openai

# How memories are retrieved at session start.
# "auto" uses vectors when available, falls back to keywords.
context:
  semantic: auto                # auto | always | never
  topup_recent: true            # also include recent memories
"""


@config.command("init")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing config")
def config_init(force):
    """Generate a starter config.yaml."""
    home = get_memory_home()
    config_path = os.path.join(home, "config.yaml")

    if os.path.exists(config_path) and not force:
        click.echo(f"Config already exists at {config_path}")
        click.echo("Use --force to overwrite.")
        return

    os.makedirs(home, exist_ok=True)
    with open(config_path, "w") as f:
        f.write(_CONFIG_TEMPLATE)

    click.echo(f"Created {config_path}")
    click.echo("Edit the file to configure your embedding provider.")


@main.command()
@click.option("--title", required=True, help="Title of the memory")
@click.option("--what", required=True, help="What happened or was learned")
@click.option("--why", default=None, help="Why it matters")
@click.option("--impact", default=None, help="Impact or consequences")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option(
    "--category",
    type=click.Choice(["decision", "pattern", "bug", "context", "learning"]),
    default=None,
    help="Category of the memory",
)
@click.option("--related-files", default="", help="Comma-separated file paths")
@click.option("--details", default=None, help="Extended details or context")
@click.option("--details-file", default=None, help="Path to a file containing extended details")
@click.option("--details-template", is_flag=True, default=False, help="Use a structured details template")
@click.option("--source", default=None, help="Source of the memory (client/IDE)")
@click.option("--agent", default=None, help="Agent role (architect, developer, reviewer, etc.)")
@click.option("--project", default=None, help="Project name")
def save(
    title,
    what,
    why,
    impact,
    tags,
    category,
    related_files,
    details,
    details_file,
    details_template,
    source,
    agent,
    project,
):
    """Save a memory to the current session."""
    project = project or os.path.basename(os.getcwd())
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    file_list = [f.strip() for f in related_files.split(",") if f.strip()] if related_files else []

    if details and details_file:
        raise click.UsageError("Use either --details or --details-file, not both.")

    resolved_details = details
    if details_file:
        try:
            with open(details_file) as f:
                resolved_details = f.read()
        except OSError as e:
            raise click.ClickException(f"Failed to read details file '{details_file}': {e}") from e

    if details_template and not (resolved_details or "").strip():
        resolved_details = DETAILS_TEMPLATE

    raw = RawMemoryInput(
        title=title,
        what=what,
        why=why,
        impact=impact,
        tags=tag_list,
        category=category,
        related_files=file_list,
        details=resolved_details,
        source=source,
        agent=agent,
    )

    svc = MemoryService()
    result = svc.save(raw, project=project)
    svc.close()

    click.echo(f"Saved: {title} (id: {result['id']})")
    click.echo(f"File: {result['file_path']}")
    for warning in result.get("warnings", []):
        click.echo(f"Warning: {warning}")


@main.command()
@click.argument("query")
@click.option("--limit", default=5, help="Maximum number of results")
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Filter to current project (current directory name)",
)
@click.option("--source", default=None, help="Filter by source (client/IDE)")
@click.option("--agent", default=None, help="Filter by agent role")
def search(query, limit, project, source, agent):
    """Search memories using hybrid FTS5 + semantic search."""
    project_name = os.path.basename(os.getcwd()) if project else None

    svc = MemoryService()
    results = svc.search(query, limit=limit, project=project_name, source=source, agent=agent)
    svc.close()

    if not results:
        click.echo("No results found.")
        return

    click.echo(f"\n Results ({len(results)} found) ")

    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        cat = r.get("category", "")
        proj = r.get("project", "")
        src = r.get("source", "")
        has_details = r.get("has_details", False)

        click.echo(f"\n [{i}] {r['title']} (score: {score:.2f})")
        click.echo(f"     {cat} | {r.get('created_at', '')[:10]} | {proj}" + (f" | {src}" if src else ""))
        click.echo(f"     What: {r['what']}")

        if r.get("why"):
            click.echo(f"     Why: {r['why']}")

        if r.get("impact"):
            click.echo(f"     Impact: {r['impact']}")

        if has_details:
            click.echo(f"     Details: available (use `memory details {r['id'][:12]}`)")


@main.command()
@click.argument("memory_id")
def details(memory_id):
    """Fetch full details for a specific memory."""
    svc = MemoryService()
    detail = svc.get_details(memory_id)
    svc.close()

    if not detail:
        click.echo(f"No details found for memory {memory_id}")
        return

    click.echo(detail.body)


@main.command()
@click.argument("memory_id")
def delete(memory_id):
    """Delete a memory by ID or prefix."""
    svc = MemoryService()
    deleted = svc.delete(memory_id)
    svc.close()

    if deleted:
        click.echo(f"Deleted memory {memory_id}")
    else:
        click.echo(f"No memory found for {memory_id}")


@main.command()
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Filter to current project (current directory name)",
)
@click.option("--source", default=None, help="Filter by source (client/IDE)")
@click.option("--agent", default=None, help="Filter by agent role")
@click.option("--limit", default=10, help="Maximum number of pointers")
@click.option("--query", default=None, help="Semantic search query for filtering")
@click.option(
    "--semantic",
    "semantic_mode",
    flag_value="always",
    default=None,
    help="Force semantic search (embeddings)",
)
@click.option(
    "--fts-only",
    "semantic_mode",
    flag_value="never",
    help="Disable embeddings and use FTS-only",
)
@click.option(
    "--show-config",
    is_flag=True,
    default=False,
    help="Show effective configuration and exit",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["hook", "agents-md"]),
    default="hook",
    help="Output format",
)
def context(project, source, agent, limit, query, semantic_mode, show_config, output_format):
    """Output memory pointers for agent context injection."""
    import json

    if show_config:
        home = get_memory_home()
        cfg = load_config(os.path.join(home, "config.yaml"))
        data = _redact_api_keys(asdict(cfg))
        data["memory_home"] = home
        click.echo(yaml.safe_dump(data, sort_keys=False))
        return

    project_name = os.path.basename(os.getcwd()) if project else None

    svc = MemoryService()
    results, total = svc.get_context(
        limit=limit,
        project=project_name,
        source=source,
        agent=agent,
        query=query,
        semantic_mode=semantic_mode,
    )
    svc.close()

    if not results:
        click.echo("No memories found.")
        return

    showing = len(results)

    if output_format == "agents-md":
        click.echo("## Memory Context\n")

    click.echo(f"Available memories ({total} total, showing {showing}):")

    for r in results:
        date_str = r.get("created_at", "")[:10]
        # Format date as "Mon DD" if possible
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str)
            date_display = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_display = date_str

        title = r.get("title", "Untitled")
        cat = r.get("category", "")
        tags_raw = r.get("tags", "")
        if isinstance(tags_raw, str) and tags_raw:
            try:
                tags_list = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags_list = []
        elif isinstance(tags_raw, list):
            tags_list = tags_raw
        else:
            tags_list = []

        cat_part = f" [{cat}]" if cat else ""
        tags_part = f" [{','.join(tags_list)}]" if tags_list else ""

        click.echo(f"- [{date_display}] {title}{cat_part}{tags_part}")

    if output_format == "agents-md":
        click.echo("")
    click.echo('Use `memory search <query>` for full details on any memory.')


@main.command()
def reindex():
    """Rebuild vector index with current embedding provider."""
    svc = MemoryService()

    total = svc.db.count_memories()
    if total == 0:
        click.echo("No memories to reindex.")
        svc.close()
        return

    click.echo(f"Reindexing {total} memories with {svc.config.embedding.provider}/{svc.config.embedding.model}...")

    def progress(current, count):
        click.echo(f"  {current}/{count}", nl=(current == count))
        if current < count:
            click.echo("\r", nl=False)

    result = svc.reindex(progress_callback=progress)
    svc.close()

    click.echo(
        f"Re-indexed {result['count']} memories with "
        f"{result['model']} ({result['dim']} dims)"
    )


@main.command()
@click.option("--limit", default=10, help="Maximum number of sessions to show")
@click.option("--project", default=None, help="Filter by project name")
def sessions(limit, project):
    """List recent sessions."""
    svc = MemoryService()
    vault = svc.vault_dir
    session_files = []

    if os.path.exists(vault):
        for proj_dir in sorted(os.listdir(vault)):
            proj_path = os.path.join(vault, proj_dir)
            if not os.path.isdir(proj_path) or proj_dir.startswith("."):
                continue
            if project and proj_dir != project:
                continue

            for f in sorted(os.listdir(proj_path), reverse=True):
                if f.endswith("-session.md"):
                    session_files.append((proj_dir, f))

    svc.close()

    if not session_files:
        click.echo("No sessions found.")
        return

    click.echo("\nSessions:")
    for proj, fname in session_files[:limit]:
        date_str = fname.replace("-session.md", "")
        click.echo(f"  {date_str} | {proj}")


def _resolve_config_dir(agent_dot_dir: str, config_dir: str | None, project: bool) -> str:
    """Resolve the config directory for an agent.

    Args:
        agent_dot_dir: The dot-directory name (e.g. ".claude", ".cursor", ".codex").
        config_dir: Explicit --config-dir override (takes priority).
        project: If True, use cwd; if False, use home directory.
    """
    if config_dir:
        return config_dir
    if project:
        return os.path.join(os.getcwd(), agent_dot_dir)
    return os.path.join(os.path.expanduser("~"), agent_dot_dir)


@main.group()
def setup():
    """Install EchoVault hooks for an agent."""
    pass


@setup.command("claude-code")
@click.option("--config-dir", default=None, help="Path to .claude directory")
@click.option("--project", is_flag=True, default=False, help="Install in current project instead of globally")
def setup_claude_code_cmd(config_dir, project):
    """Install hooks into Claude Code settings."""
    from memory.setup import setup_claude_code

    target = _resolve_config_dir(".claude", config_dir, project)
    result = setup_claude_code(target, project=project)
    click.echo(result["message"])


@setup.command("cursor")
@click.option("--config-dir", default=None, help="Path to .cursor directory")
@click.option("--project", is_flag=True, default=False, help="Install in current project instead of globally")
def setup_cursor_cmd(config_dir, project):
    """Install hooks into Cursor hooks.json."""
    from memory.setup import setup_cursor

    target = _resolve_config_dir(".cursor", config_dir, project)
    result = setup_cursor(target)
    click.echo(result["message"])


@setup.command("codex")
@click.option("--config-dir", default=None, help="Path to .codex directory")
@click.option("--project", is_flag=True, default=False, help="Install in current project instead of globally")
def setup_codex_cmd(config_dir, project):
    """Install EchoVault section into Codex AGENTS.md and config.toml."""
    from memory.setup import setup_codex

    target = _resolve_config_dir(".codex", config_dir, project)
    result = setup_codex(target)
    click.echo(result["message"])


@setup.command("opencode")
@click.option("--project", is_flag=True, default=False, help="Install in current project instead of globally")
def setup_opencode_cmd(project):
    """Install EchoVault MCP server into OpenCode."""
    from memory.setup import setup_opencode

    result = setup_opencode(project=project)
    click.echo(result["message"])


@main.group()
def uninstall():
    """Remove EchoVault hooks for an agent."""
    pass


@uninstall.command("claude-code")
@click.option("--config-dir", default=None, help="Path to .claude directory")
@click.option("--project", is_flag=True, default=False, help="Uninstall from current project instead of globally")
def uninstall_claude_code_cmd(config_dir, project):
    """Remove hooks from Claude Code settings."""
    from memory.setup import uninstall_claude_code

    target = _resolve_config_dir(".claude", config_dir, project)
    result = uninstall_claude_code(target, project=project)
    click.echo(result["message"])


@uninstall.command("cursor")
@click.option("--config-dir", default=None, help="Path to .cursor directory")
@click.option("--project", is_flag=True, default=False, help="Uninstall from current project instead of globally")
def uninstall_cursor_cmd(config_dir, project):
    """Remove hooks from Cursor hooks.json."""
    from memory.setup import uninstall_cursor

    target = _resolve_config_dir(".cursor", config_dir, project)
    result = uninstall_cursor(target)
    click.echo(result["message"])


@uninstall.command("codex")
@click.option("--config-dir", default=None, help="Path to .codex directory")
@click.option("--project", is_flag=True, default=False, help="Uninstall from current project instead of globally")
def uninstall_codex_cmd(config_dir, project):
    """Remove EchoVault from Codex AGENTS.md and config.toml."""
    from memory.setup import uninstall_codex

    target = _resolve_config_dir(".codex", config_dir, project)
    result = uninstall_codex(target)
    click.echo(result["message"])


@uninstall.command("opencode")
@click.option("--project", is_flag=True, default=False, help="Uninstall from current project instead of globally")
def uninstall_opencode_cmd(project):
    """Remove EchoVault from OpenCode."""
    from memory.setup import uninstall_opencode

    result = uninstall_opencode(project=project)
    click.echo(result["message"])


@main.group()
def user():
    """Manage users (PostgreSQL backend only)."""
    pass


@user.command("add")
@click.argument("name")
def user_add(name):
    """Create a new user and print their auth token."""
    from memory.config import get_memory_home, load_config
    home = get_memory_home()
    config = load_config(os.path.join(home, "config.yaml"))

    if config.storage.backend != "postgresql":
        click.echo("Error: user management requires PostgreSQL backend", err=True)
        click.echo("Set storage.backend = postgresql in config.yaml", err=True)
        return

    from memory.db_pg import MemoryDBPostgres
    db = MemoryDBPostgres(config.storage.url, user_id=None)

    try:
        user_id, token = db.create_user(name)
        click.echo(f"User created: {name} (id={user_id})")
        click.echo(f"Token: {token}")
        click.echo("")
        click.echo("Save this token! Add it to config.yaml:")
        click.echo("auth:")
        click.echo(f"  token: {token}")
    except Exception as e:
        click.echo(f"Error creating user: {e}", err=True)
    finally:
        db.close()


@user.command("list")
def user_list():
    """List all users."""
    from memory.config import get_memory_home, load_config
    home = get_memory_home()
    config = load_config(os.path.join(home, "config.yaml"))

    if config.storage.backend != "postgresql":
        click.echo("Error: user management requires PostgreSQL backend", err=True)
        return

    from memory.db_pg import MemoryDBPostgres
    db = MemoryDBPostgres(config.storage.url, user_id=None)

    try:
        users = db.list_users()
        if not users:
            click.echo("No users found.")
        else:
            click.echo(f"Total users: {len(users)}")
            for u in users:
                created = u.get("created_at", "")[:10] if u.get("created_at") else "unknown"
                click.echo(f"  {u['id']:3d}  {u['name']:20s}  (created: {created})")
    except Exception as e:
        click.echo(f"Error listing users: {e}", err=True)
    finally:
        db.close()


@main.group()
def project():
    """Manage projects (PostgreSQL backend only)."""
    pass


@project.command("register")
@click.argument("name")
@click.option("--display-name", default=None, help="Human-readable project name")
@click.option("--description", default=None, help="Project description")
def project_register(name, display_name, description):
    """Register a new project."""
    svc = MemoryService()
    try:
        result = svc.register_project(name, display_name, description)
        click.echo(f"Project registered: {result['name']}")
        if result.get("display_name"):
            click.echo(f"Display name: {result['display_name']}")
    except NotImplementedError:
        click.echo("Error: project registration requires PostgreSQL backend", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@project.command("list")
def project_list():
    """List all registered projects."""
    svc = MemoryService()
    try:
        projects = svc.list_projects()
        if not projects:
            click.echo("No projects registered.")
        else:
            click.echo(f"Registered projects ({len(projects)}):")
            for p in projects:
                display = f" ({p['display_name']})" if p.get("display_name") else ""
                created = str(p.get("created_at", ""))[:10]
                click.echo(f"  {p['name']}{display}  (created: {created})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@project.command("auto-register")
def project_auto_register():
    """Bulk-register all project names from existing memories."""
    svc = MemoryService()
    try:
        count = svc.auto_register_projects()
        click.echo(f"Auto-registered {count} project(s).")
    except NotImplementedError:
        click.echo("Error: project registration requires PostgreSQL backend", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@main.group()
def todo():
    """Manage TODO items (PostgreSQL backend only)."""
    pass


@todo.command("add")
@click.argument("title")
@click.option("--description", default=None, help="Detailed description")
@click.option("--project", default=None, help="Project name (default: current directory)")
@click.option("--priority", type=click.Choice(["0", "1", "2"]), default="0", help="0=normal, 1=high, 2=critical")
def todo_add(title, description, project, priority):
    """Add a TODO item to a project."""
    project = project or os.path.basename(os.getcwd())
    svc = MemoryService()
    try:
        result = svc.add_todo(project, title, description, int(priority))
        click.echo(f"TODO added: #{result['id']} {result['title']}")
    except NotImplementedError:
        click.echo("Error: TODOs require PostgreSQL backend", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@todo.command("list")
@click.option("--project", default=None, help="Project name (default: current directory)")
@click.option("--all", "include_done", is_flag=True, default=False, help="Include done/cancelled items")
def todo_list_cmd(project, include_done):
    """List TODO items for a project."""
    project = project or os.path.basename(os.getcwd())
    svc = MemoryService()
    try:
        statuses = ["pending", "in_progress", "done", "cancelled"] if include_done else None
        todos = svc.list_todos(project, statuses)
        if not todos:
            click.echo(f"No TODOs for project '{project}'.")
        else:
            click.echo(f"TODOs for '{project}' ({len(todos)}):")
            for t in todos:
                status_icon = {"pending": " ", "in_progress": ">", "done": "x", "cancelled": "-"}.get(t["status"], "?")
                priority_str = {1: " [HIGH]", 2: " [CRITICAL]"}.get(t.get("priority", 0), "")
                click.echo(f"  [{status_icon}] #{t['id']} {t['title']}{priority_str}")
                if t.get("description"):
                    click.echo(f"      {t['description'][:80]}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@todo.command("update")
@click.argument("todo_id", type=int)
@click.option("--status", type=click.Choice(["pending", "in_progress", "done", "cancelled"]), default=None)
@click.option("--title", default=None)
@click.option("--description", default=None)
@click.option("--priority", type=click.Choice(["0", "1", "2"]), default=None)
def todo_update(todo_id, status, title, description, priority):
    """Update a TODO item."""
    svc = MemoryService()
    try:
        result = svc.update_todo(
            todo_id,
            status=status,
            title=title,
            description=description,
            priority=int(priority) if priority else None,
        )
        if result:
            click.echo(f"TODO #{todo_id} updated: {result['status']}")
        else:
            click.echo(f"TODO #{todo_id} not found.", err=True)
    except NotImplementedError:
        click.echo("Error: TODOs require PostgreSQL backend", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


@todo.command("done")
@click.argument("todo_id", type=int)
def todo_done(todo_id):
    """Mark a TODO as done."""
    svc = MemoryService()
    try:
        result = svc.update_todo(todo_id, status="done")
        if result:
            click.echo(f"TODO #{todo_id} marked as done.")
        else:
            click.echo(f"TODO #{todo_id} not found.", err=True)
    except NotImplementedError:
        click.echo("Error: TODOs require PostgreSQL backend", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# Bundle install / status / update commands
# ---------------------------------------------------------------------------

@main.group()
def install():
    """Install skill bundle from MCP server into current project."""
    pass


@install.command("claude-code")
@click.option("--url", default=None, help="MCP server URL (or CODEVAULT_URL env)")
@click.option("--token", default=None, help="Bearer auth token (or CODEVAULT_TOKEN env)")
@click.option("--project-name", default=None, help="Project name (auto-detected from directory)")
@click.option("--offline", is_flag=True, default=False, help="Use bundled content (no server needed)")
def install_claude_code(url, token, project_name, offline):
    """Install Claude Code skill bundle (skills, hooks, settings, MCP config)."""
    from memory.installer import (
        fetch_bundle,
        fetch_bundle_local,
        install_bundle,
        resolve_connection_params,
    )

    project_dir = os.getcwd()

    if offline:
        bundle = fetch_bundle_local("claude-code")
        result = install_bundle(
            bundle, project_dir,
            project_name=project_name or "",
        )
        click.echo(result.message)
        return

    # Resolve URL and token from args, env, or existing config
    if not url or not token:
        auto_url, auto_token = resolve_connection_params(project_dir)
        url = url or auto_url
        token = token or auto_token

    if not url or not token:
        click.echo("Error: --url and --token are required (or set CODEVAULT_URL / CODEVAULT_TOKEN)", err=True)
        click.echo("Use --offline to install from local package without a server.", err=True)
        return

    try:
        bundle = fetch_bundle(url, token, "claude-code")
    except RuntimeError as e:
        click.echo(f"Error fetching bundle: {e}", err=True)
        return

    result = install_bundle(
        bundle, project_dir,
        server_url=url,
        auth_token=token,
        project_name=project_name or "",
    )
    click.echo(result.message)
    for w in result.warnings:
        click.echo(f"  Warning: {w}")
    if result.files_written:
        click.echo(f"  Files: {', '.join(result.files_written)}")


@main.command("status")
def bundle_status():
    """Check installed bundle status vs server."""
    from memory.installer import check_status, resolve_connection_params

    project_dir = os.getcwd()
    url, token = resolve_connection_params(project_dir)
    result = check_status(project_dir, url, token)

    click.echo(result.message)
    if result.modified_files:
        click.echo("  Modified files:")
        for f in result.modified_files:
            click.echo(f"    - {f}")
    if result.server_version > result.local_version:
        click.echo(f"  Run 'memory update' to upgrade to v{result.server_version}")


@main.command("update")
@click.option("--force", is_flag=True, default=False, help="Overwrite locally modified files")
@click.option("--check", "dry_run", is_flag=True, default=False, help="Dry run — show what would change")
def bundle_update(force, dry_run):
    """Update installed bundle from MCP server."""
    from memory.installer import update_bundle, resolve_connection_params

    project_dir = os.getcwd()
    url, token = resolve_connection_params(project_dir)

    if not url or not token:
        click.echo("Error: cannot resolve server URL and token", err=True)
        click.echo("Set CODEVAULT_URL / CODEVAULT_TOKEN or install first.", err=True)
        return

    result = update_bundle(project_dir, url, token, force=force, dry_run=dry_run)
    click.echo(result.message)
    if result.conflicts:
        click.echo("  Conflicts:")
        for f in result.conflicts:
            click.echo(f"    - {f}")
    if result.files_updated:
        click.echo(f"  Updated: {', '.join(result.files_updated)}")


@main.command()
@click.option("--transport", type=click.Choice(["stdio", "sse", "http"]), default="stdio", help="Transport type")
@click.option("--port", type=int, default=8420, help="Port for SSE/HTTP transport")
@click.option("--host", default="127.0.0.1", help="Host for SSE/HTTP transport")
def mcp(transport, port, host):
    """Start the EchoVault MCP server."""
    import asyncio

    if transport == "stdio":
        from memory.mcp_server import run_server
        asyncio.run(run_server())
    elif transport == "http":
        # Streamable HTTP transport (MCP 2025-03-26 spec) — stateful sessions
        from memory.mcp_server_sse import create_server, resolve_user_id_from_token
        from memory.config import get_memory_home, load_config
        from mcp.server.streamable_http import StreamableHTTPServerTransport
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        import contextlib
        import anyio
        import uvicorn
        import uuid

        home = get_memory_home()
        config = load_config(os.path.join(home, "config.yaml"))

        # Disable DNS rebinding protection — we serve behind nginx/IP
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

        # Stateful session store: session_id -> {transport, server, service}
        sessions: dict[str, dict] = {}
        # App-level task group — set in lifespan, used to spawn session tasks
        app_task_group: anyio.abc.TaskGroup | None = None

        def _auth_user(request: Request) -> tuple[int | None, str | None]:
            """Extract and validate Bearer token, return (user_id, error_msg)."""
            auth_header = request.headers.get("Authorization", "")
            token = auth_header[7:] if auth_header.startswith("Bearer ") else None
            if not token:
                click.echo(f"[AUTH] No token from {request.client.host}")
                if config.storage.backend == "postgresql":
                    return None, "Token required"
                return None, None
            if config.storage.backend == "postgresql":
                user_id = resolve_user_id_from_token(token)
                if not user_id:
                    click.echo(f"[AUTH] Invalid token from {request.client.host}")
                    return None, "Invalid token"
                click.echo(f"[AUTH] User {user_id} from {request.client.host}")
                return user_id, None
            return None, None

        async def handle_mcp(scope, receive, send):
            """Raw ASGI handler — transport.handle_request writes directly to send."""
            nonlocal app_task_group
            request = Request(scope, receive, send)
            session_id = request.headers.get("mcp-session-id")

            # Case 1: Existing session — route to its transport
            if session_id and session_id in sessions:
                session = sessions[session_id]
                try:
                    await session["transport"].handle_request(scope, receive, send)
                except Exception as e:
                    click.echo(f"[ERROR] Session {session_id}: {e}")
                    sessions.pop(session_id, None)
                    session["service"].close()
                return

            # Case 2: No session or unknown session ID — create new session
            is_reconnect = bool(session_id and session_id not in sessions)
            if is_reconnect:
                click.echo(f"[SESSION] Reconnect {session_id}")
            user_id, error = _auth_user(request)
            if error:
                response = JSONResponse({"error": error}, status_code=401)
                await response(scope, receive, send)
                return

            # Reuse client's session ID if provided (reconnect after server restart)
            new_session_id = session_id if session_id else uuid.uuid4().hex
            server, service = create_server(user_id=user_id)
            http_transport = StreamableHTTPServerTransport(
                mcp_session_id=new_session_id,
                security_settings=security,
            )

            async def run_session(*, task_status=anyio.TASK_STATUS_IGNORED):
                try:
                    async with http_transport.connect() as (read_stream, write_stream):
                        sessions[new_session_id] = {
                            "transport": http_transport,
                            "server": server,
                            "service": service,
                        }
                        click.echo(f"[SESSION] Started {new_session_id}")
                        task_status.started()
                        await server.run(
                            read_stream, write_stream,
                            server.create_initialization_options(),
                            # Skip init requirement for reconnect (client won't re-send initialize)
                            stateless=is_reconnect,
                        )
                except Exception as e:
                    click.echo(f"[ERROR] Session {new_session_id}: {e}")
                finally:
                    sessions.pop(new_session_id, None)
                    service.close()
                    click.echo(f"[SESSION] Closed {new_session_id}")

            # Start server.run() in background, wait until transport is ready
            await app_task_group.start(run_session)
            # Now handle the initialize request
            await http_transport.handle_request(scope, receive, send)

        @contextlib.asynccontextmanager
        async def lifespan(app):
            nonlocal app_task_group
            async with anyio.create_task_group() as tg:
                app_task_group = tg
                click.echo(f"Starting MCP server on {host}:{port} (Streamable HTTP)")
                yield
                # On shutdown: cancel all session tasks
                tg.cancel_scope.cancel()
                for sid, session in sessions.items():
                    session["service"].close()
                sessions.clear()

        # --- Bundle REST endpoints ---
        async def handle_bundles_list(request: Request):
            """GET /bundles — list available skill bundles."""
            user_id, error = _auth_user(request)
            if error:
                return JSONResponse({"error": error}, status_code=401)
            from memory.bundles import list_bundles
            return JSONResponse(list_bundles())

        async def handle_bundle_get(request: Request):
            """GET /bundles/{agent_type} — return full bundle manifest."""
            user_id, error = _auth_user(request)
            if error:
                return JSONResponse({"error": error}, status_code=401)
            agent_type = request.path_params["agent_type"]
            from memory.bundles import get_bundle
            bundle = get_bundle(agent_type)
            if not bundle:
                return JSONResponse({"error": f"Bundle '{agent_type}' not found"}, status_code=404)
            return JSONResponse(bundle)

        app = Starlette(
            routes=[
                Route("/bundles", endpoint=handle_bundles_list),
                Route("/bundles/{agent_type}", endpoint=handle_bundle_get),
                Mount("", app=handle_mcp),
            ],
            lifespan=lifespan,
            middleware=[
                Middleware(
                    CORSMiddleware,
                    allow_origins=["*"],
                    allow_methods=["GET", "POST", "DELETE"],
                    expose_headers=["Mcp-Session-Id"],
                ),
            ],
        )
        uvicorn.run(app, host=host, port=port)
    else:
        # SSE transport (deprecated — use --transport http instead)
        from memory.mcp_server_sse import create_server, resolve_user_id_from_token
        from memory.config import get_memory_home, load_config
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Mount, Route
        import uvicorn

        home = get_memory_home()
        config = load_config(os.path.join(home, "config.yaml"))

        # Create SSE transport at app level — shared across all connections
        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            # Token-based auth for multi-user mode
            auth_header = request.headers.get("Authorization", "")
            token = None
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

            user_id = None
            if token and config.storage.backend == "postgresql":
                user_id = resolve_user_id_from_token(token)
                if not user_id:
                    click.echo(f"[AUTH] Invalid token from {request.client.host}")
                    return JSONResponse({"error": "Invalid token"}, status_code=401)
                click.echo(f"[AUTH] User {user_id} connected from {request.client.host}")
            elif not token:
                click.echo(f"[AUTH] No token from {request.client.host}")

            server, service = create_server(user_id=user_id)

            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                try:
                    await server.run(
                        streams[0], streams[1],
                        server.create_initialization_options()
                    )
                finally:
                    service.close()

            return Response()

        # --- Bundle REST endpoints (SSE transport) ---
        async def handle_bundles_list_sse(request: Request):
            auth_header = request.headers.get("Authorization", "")
            token = auth_header[7:] if auth_header.startswith("Bearer ") else None
            if not token and config.storage.backend == "postgresql":
                return JSONResponse({"error": "Token required"}, status_code=401)
            if token and config.storage.backend == "postgresql":
                uid = resolve_user_id_from_token(token)
                if not uid:
                    return JSONResponse({"error": "Invalid token"}, status_code=401)
            from memory.bundles import list_bundles
            return JSONResponse(list_bundles())

        async def handle_bundle_get_sse(request: Request):
            auth_header = request.headers.get("Authorization", "")
            token = auth_header[7:] if auth_header.startswith("Bearer ") else None
            if not token and config.storage.backend == "postgresql":
                return JSONResponse({"error": "Token required"}, status_code=401)
            if token and config.storage.backend == "postgresql":
                uid = resolve_user_id_from_token(token)
                if not uid:
                    return JSONResponse({"error": "Invalid token"}, status_code=401)
            agent_type = request.path_params["agent_type"]
            from memory.bundles import get_bundle
            bundle = get_bundle(agent_type)
            if not bundle:
                return JSONResponse({"error": f"Bundle '{agent_type}' not found"}, status_code=404)
            return JSONResponse(bundle)

        app = Starlette(routes=[
            Route("/bundles", endpoint=handle_bundles_list_sse),
            Route("/bundles/{agent_type}", endpoint=handle_bundle_get_sse),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ])
        click.echo(f"Starting MCP server on {host}:{port} (SSE transport, deprecated)")
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
