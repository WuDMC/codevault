"""MCP server with SSE/HTTP transport and multi-user auth support."""

import os
from typing import Optional

from memory.core import MemoryService
from memory.mcp_handlers import create_mcp_server


def create_server(user_id: Optional[int] = None) -> tuple:
    """Create and configure the MCP server with memory tools.

    Args:
        user_id: User ID for PostgreSQL backend (required for multi-user mode)

    Returns:
        Tuple of (Server, MemoryService)
    """
    service = MemoryService(user_id=user_id)
    server = create_mcp_server(service)
    return server, service


def resolve_user_id_from_token(token: str) -> Optional[int]:
    """Resolve user_id from auth token (PostgreSQL backend only).

    Args:
        token: User auth token

    Returns:
        User ID or None if invalid
    """
    from memory.config import get_memory_home, load_config
    home = get_memory_home()
    config = load_config(os.path.join(home, "config.yaml"))

    if config.storage.backend != "postgresql":
        return None

    from memory.db_pg import MemoryDBPostgres
    db = MemoryDBPostgres(config.storage.url, user_id=None)
    user = db.get_user_by_token(token)
    db.close()

    if user:
        return user["id"]
    return None
