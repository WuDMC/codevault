"""MCP server with stdio transport for local usage."""

from mcp.server.stdio import stdio_server

from memory.core import MemoryService
from memory.mcp_handlers import create_mcp_server


async def run_server():
    """Run the MCP server with stdio transport."""
    service = MemoryService()
    try:
        server = create_mcp_server(service)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        service.close()
