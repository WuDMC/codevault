"""Client-side bundle installer — fetches from server and writes to project.

Usage:
    from memory.installer import fetch_bundle, install_bundle, check_status, update_bundle
"""

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class InstallResult:
    success: bool
    files_written: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class StatusResult:
    installed: bool
    bundle_name: str = ""
    local_version: int = 0
    server_version: int = 0
    up_to_date: bool = False
    modified_files: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class UpdateResult:
    success: bool
    files_updated: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# JSON helpers (reuse pattern from setup.py)
# ---------------------------------------------------------------------------

def _read_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _file_hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

def _resolve_templates(content: str, params: dict[str, str]) -> str:
    """Replace {{key}} placeholders with values from params."""
    result = content
    for key, value in params.items():
        result = result.replace("{{" + key + "}}", value)
    return result


# ---------------------------------------------------------------------------
# Fetch bundle from server
# ---------------------------------------------------------------------------

def fetch_bundle(server_url: str, token: str, agent_type: str = "claude-code") -> dict:
    """Fetch a bundle manifest from the MCP server.

    Args:
        server_url: Base URL of the MCP server (e.g. https://memory.wudmc.com)
        token: Bearer auth token
        agent_type: Bundle type to fetch (default: claude-code)

    Returns:
        Bundle manifest dict

    Raises:
        RuntimeError: If fetch fails
    """
    import httpx

    url = f"{server_url.rstrip('/')}/bundles/{agent_type}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        if resp.status_code == 401:
            raise RuntimeError("Authentication failed — check your token")
        if resp.status_code == 404:
            raise RuntimeError(f"Bundle '{agent_type}' not found on server")
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as e:
        raise RuntimeError(f"Cannot connect to {server_url}: {e}") from e


def fetch_bundle_local(agent_type: str = "claude-code") -> dict:
    """Get bundle from local Python package (no server needed).

    Useful for offline install or local-only mode.
    """
    from memory.bundles import get_bundle
    bundle = get_bundle(agent_type)
    if not bundle:
        raise RuntimeError(f"Bundle '{agent_type}' not found locally")
    return bundle


# ---------------------------------------------------------------------------
# Install bundle into project
# ---------------------------------------------------------------------------

def install_bundle(
    bundle: dict,
    project_dir: str,
    *,
    server_url: str = "",
    auth_token: str = "",
    project_name: str = "",
) -> InstallResult:
    """Install a bundle into a project directory.

    Args:
        bundle: Bundle manifest dict (from fetch_bundle or fetch_bundle_local)
        project_dir: Root directory of the project
        server_url: MCP server URL (for .mcp.json and template resolution)
        auth_token: Bearer token (for .mcp.json and template resolution)
        project_name: Project name (for template resolution, auto-detected if empty)

    Returns:
        InstallResult with details of what was written
    """
    result = InstallResult(success=True)
    claude_dir = os.path.join(project_dir, ".claude")

    # Auto-detect project name
    if not project_name:
        project_name = os.path.basename(os.path.abspath(project_dir))

    # Template params
    params = {
        "server_url": server_url.rstrip("/") if server_url else "",
        "auth_token": auth_token,
        "project_name": project_name,
    }

    # 1. Write bundle files (skills + hooks)
    file_hashes = {}
    for rel_path, file_info in bundle.get("files", {}).items():
        content = file_info["content"]
        if file_info.get("template"):
            content = _resolve_templates(content, params)

        abs_path = os.path.join(claude_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(content)

        if file_info.get("executable"):
            st = os.stat(abs_path)
            os.chmod(abs_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        file_hashes[rel_path] = _file_hash(content)
        result.files_written.append(rel_path)

    # 2. Merge settings.local.json (only hooks key)
    settings_path = os.path.join(claude_dir, "settings.local.json")
    settings = _read_json(settings_path)

    # Backup existing settings before modifying
    if os.path.exists(settings_path):
        shutil.copy2(settings_path, settings_path + ".bak")

    # Merge hooks — replace managed hooks, preserve user hooks
    bundle_hooks = bundle.get("settings_hooks", {})
    if bundle_hooks:
        existing_hooks = settings.get("hooks", {})
        merged_hooks = _merge_hooks(existing_hooks, bundle_hooks)
        settings["hooks"] = merged_hooks

    settings["enableAllProjectMcpServers"] = True
    _write_json(settings_path, settings)
    result.files_written.append("settings.local.json")

    # 3. Merge .mcp.json (add memory server entry, preserve others)
    if server_url and auth_token:
        mcp_path = os.path.join(project_dir, ".mcp.json")
        mcp_data = _read_json(mcp_path)
        servers = mcp_data.setdefault("mcpServers", {})

        mcp_config = bundle.get("mcp_config", {})
        if mcp_config:
            resolved_config = {}
            for key, value in mcp_config.items():
                if isinstance(value, str):
                    resolved_config[key] = _resolve_templates(value, params)
                elif isinstance(value, dict):
                    resolved_config[key] = {
                        k: _resolve_templates(v, params) if isinstance(v, str) else v
                        for k, v in value.items()
                    }
                else:
                    resolved_config[key] = value
            servers["memory"] = resolved_config

        _write_json(mcp_path, mcp_data)
        result.files_written.append("../.mcp.json")

    # 4. Append .gitignore lines
    gitignore_path = os.path.join(project_dir, ".gitignore")
    gitignore_lines = bundle.get("gitignore_lines", [])
    if gitignore_lines:
        existing = ""
        try:
            with open(gitignore_path) as f:
                existing = f.read()
        except FileNotFoundError:
            pass

        new_lines = [line for line in gitignore_lines if line not in existing]
        if new_lines:
            with open(gitignore_path, "a") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(new_lines) + "\n")

    # 5. Write manifest
    manifest = {
        "bundle": bundle.get("name", "claude-code"),
        "version": bundle.get("version", 0),
        "content_hash": bundle.get("content_hash", ""),
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "server_url": server_url,
        "files": file_hashes,
    }
    manifest_path = os.path.join(claude_dir, ".codevault-manifest.json")
    _write_json(manifest_path, manifest)

    result.message = f"Installed bundle '{bundle.get('name')}' v{bundle.get('version')} ({len(result.files_written)} files)"
    return result


def _merge_hooks(existing: dict, bundle_hooks: dict) -> dict:
    """Merge bundle hooks into existing hooks config.

    Strategy: for each event type, replace hooks whose commands reference
    .claude/hooks/ (managed), preserve all others (user-owned).
    """
    merged = {}

    # Start with all existing event types
    all_events = set(list(existing.keys()) + list(bundle_hooks.keys()))

    for event in all_events:
        existing_groups = existing.get(event, [])
        bundle_groups = bundle_hooks.get(event, [])

        if not bundle_groups:
            # No bundle hooks for this event — keep existing as-is
            merged[event] = existing_groups
            continue

        # Separate user hooks from managed hooks in existing config
        user_groups = []
        for group in existing_groups:
            if not _is_managed_hook_group(group):
                user_groups.append(group)

        # Bundle hooks replace all managed hooks, user hooks preserved
        merged[event] = bundle_groups + user_groups

    return merged


def _is_managed_hook_group(group: dict) -> bool:
    """Check if a hook group was installed by the bundle system."""
    for hook in group.get("hooks", []):
        cmd = hook.get("command", "")
        if ".claude/hooks/" in cmd:
            return True
    return False


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def check_status(
    project_dir: str,
    server_url: str = "",
    token: str = "",
) -> StatusResult:
    """Check installed bundle status vs server.

    Args:
        project_dir: Root directory of the project
        server_url: MCP server URL (optional — if provided, checks for updates)
        token: Bearer token (optional)

    Returns:
        StatusResult with version comparison and modified file list
    """
    claude_dir = os.path.join(project_dir, ".claude")
    manifest_path = os.path.join(claude_dir, ".codevault-manifest.json")

    manifest = _read_json(manifest_path)
    if not manifest:
        return StatusResult(installed=False, message="No bundle installed in this project")

    result = StatusResult(
        installed=True,
        bundle_name=manifest.get("bundle", "unknown"),
        local_version=manifest.get("version", 0),
    )

    # Check for locally modified files
    for rel_path, expected_hash in manifest.get("files", {}).items():
        abs_path = os.path.join(claude_dir, rel_path)
        try:
            with open(abs_path) as f:
                current_hash = _file_hash(f.read())
            if current_hash != expected_hash:
                result.modified_files.append(rel_path)
        except FileNotFoundError:
            result.modified_files.append(f"{rel_path} (missing)")

    # Check server version if URL provided
    if server_url and token:
        try:
            server_bundle = fetch_bundle(server_url, token, result.bundle_name)
            result.server_version = server_bundle.get("version", 0)
            result.up_to_date = (
                result.local_version >= result.server_version
                and not result.modified_files
            )
        except RuntimeError:
            result.server_version = -1  # couldn't reach server

    if not result.modified_files and (not server_url or result.up_to_date):
        result.message = f"Bundle '{result.bundle_name}' v{result.local_version} — up to date"
    elif result.modified_files:
        result.message = (
            f"Bundle '{result.bundle_name}' v{result.local_version} — "
            f"{len(result.modified_files)} file(s) modified locally"
        )
    elif result.server_version > result.local_version:
        result.message = (
            f"Bundle '{result.bundle_name}' v{result.local_version} — "
            f"update available (v{result.server_version})"
        )
    else:
        result.message = f"Bundle '{result.bundle_name}' v{result.local_version}"

    return result


# ---------------------------------------------------------------------------
# Update bundle
# ---------------------------------------------------------------------------

def update_bundle(
    project_dir: str,
    server_url: str,
    token: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> UpdateResult:
    """Update installed bundle from server.

    Args:
        project_dir: Root directory of the project
        server_url: MCP server URL
        token: Bearer token
        force: Overwrite locally modified files without warning
        dry_run: Show what would change without writing

    Returns:
        UpdateResult with details
    """
    status = check_status(project_dir, server_url, token)
    if not status.installed:
        return UpdateResult(success=False, message="No bundle installed — use 'memory install' first")

    # Check for conflicts
    if status.modified_files and not force:
        return UpdateResult(
            success=False,
            conflicts=status.modified_files,
            message=(
                f"Locally modified files would be overwritten: {', '.join(status.modified_files)}. "
                f"Use --force to overwrite."
            ),
        )

    if status.up_to_date and not force:
        return UpdateResult(success=True, message="Already up to date")

    if dry_run:
        bundle = fetch_bundle(server_url, token, status.bundle_name)
        return UpdateResult(
            success=True,
            files_updated=list(bundle.get("files", {}).keys()),
            message=f"Would update to v{bundle.get('version')} ({len(bundle.get('files', {}))} files)",
        )

    # Fetch and re-install
    bundle = fetch_bundle(server_url, token, status.bundle_name)
    manifest = _read_json(os.path.join(project_dir, ".claude", ".codevault-manifest.json"))

    install_result = install_bundle(
        bundle,
        project_dir,
        server_url=server_url,
        auth_token=token,
    )

    return UpdateResult(
        success=install_result.success,
        files_updated=install_result.files_written,
        message=f"Updated to v{bundle.get('version')} ({len(install_result.files_written)} files)",
    )


# ---------------------------------------------------------------------------
# Resolve connection params from existing config
# ---------------------------------------------------------------------------

def resolve_connection_params(project_dir: str) -> tuple[str, str]:
    """Try to resolve server_url and token from existing project config.

    Checks in order:
    1. Environment variables CODEVAULT_URL / CODEVAULT_TOKEN
    2. .mcp.json in project directory
    3. ~/.memory/config.yaml

    Returns:
        (server_url, token) — either or both may be empty
    """
    # 1. Environment variables
    url = os.environ.get("CODEVAULT_URL", "")
    token = os.environ.get("CODEVAULT_TOKEN", "")
    if url and token:
        return url, token

    # 2. .mcp.json
    mcp_path = os.path.join(project_dir, ".mcp.json")
    mcp_data = _read_json(mcp_path)
    memory_server = mcp_data.get("mcpServers", {}).get("memory", {})
    if memory_server:
        server_url = memory_server.get("url", "")
        # Extract base URL (remove /mcp or /sse suffix)
        for suffix in ("/mcp", "/sse"):
            if server_url.endswith(suffix):
                server_url = server_url[: -len(suffix)]
                break
        url = url or server_url

        auth_header = memory_server.get("headers", {}).get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = token or auth_header[7:]

    return url, token
