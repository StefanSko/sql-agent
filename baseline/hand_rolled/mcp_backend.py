from __future__ import annotations

import json

from fastmcp import Client, FastMCP


class FastMcpBackend:
    _server: FastMCP

    def __init__(self, server: FastMCP) -> None:
        self._server = server

    async def tool_definitions(self) -> tuple[dict[str, object], ...]:
        async with Client(self._server) as client:
            tools = await client.list_tools()
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in tools
        )

    async def call(self, name: str, arguments: dict[str, object]) -> str:
        async with Client(self._server) as client:
            result = await client.call_tool(name, arguments)
        if result.is_error:
            return "tool failed safely"
        return json.dumps(result.structured_content, separators=(",", ":"))
