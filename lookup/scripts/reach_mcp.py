# -*- coding: utf-8 -*-
"""
Lookup Agent Reach status compatibility adapter. Derived from Agent Reach (MIT).

Run through scripts/reach.py mcp in its verified private runtime.

This adapter exposes status only through native Agent Reach 1.6 doctor.
Search and reading use the integrated channel actions selected by lookup;
they are outside this MCP interface.
"""

import asyncio
import json
import sys

from agent_reach.runtime.manage import doctor
from agent_reach.utils.text import scrub_url_credentials

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = hasattr(Server, "list_tools") and hasattr(Server, "call_tool")
except ImportError:
    HAS_MCP = False


def create_server():
    if not HAS_MCP:
        print(
            "Compatible MCP SDK missing (>=1.0,<2). Install it in the verified "
            "lookup private runtime, then retry scripts/reach.py mcp.",
            file=sys.stderr,
        )
        sys.exit(1)

    server = Server("agent-reach")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_status",
                 description="Get Agent Reach status: which channels are installed and active.",
                 inputSchema={"type": "object", "properties": {}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "get_status":
                result = doctor()
            else:
                result = f"Unknown tool: {name}"

            text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
            return [TextContent(type="text", text=text)]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error: {scrub_url_credentials(e)}",
                )
            ]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
