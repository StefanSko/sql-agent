from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from fastmcp import Client
from pydantic import TypeAdapter
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset, FilteredToolset

from sql_agent.db_mcp import DbMcp
from sql_agent.mcp_client import parse_tool_result
from sql_agent.types import Catalog, ExposureMode

DepsT = TypeVar("DepsT")


@dataclass(frozen=True)
class ExposureSetup:
    toolset: AbstractToolset[object]
    instructions: str


async def prepare_exposure(db_mcp: DbMcp, mode: ExposureMode) -> ExposureSetup:
    mcp = MCPToolset(db_mcp.server, tool_error_behavior="failed", prefer_tasks=False)
    match mode:
        case ExposureMode.GRANULAR:
            included = frozenset({"list_tables", "describe_table", "run_query"})
            instructions = "Discover the schema with the available tools before writing SQL."
        case ExposureMode.CATALOG:
            included = frozenset({"get_catalog", "run_query"})
            instructions = "Retrieve the catalog with the available tool before writing SQL."
        case ExposureMode.PREFETCHED:
            included = frozenset({"run_query"})
            catalog = await _prefetch_catalog(db_mcp)
            encoded = TypeAdapter(Catalog).dump_json(catalog).decode("utf-8")
            instructions = (
                "The catalog below was fetched through MCP for this run. Use it to write SQL.\n"
                f"<catalog>{encoded}</catalog>"
            )
    return ExposureSetup(
        toolset=FilteredToolset(mcp, lambda _ctx, tool: tool.name in included),
        instructions=instructions,
    )


async def _prefetch_catalog(db_mcp: DbMcp) -> Catalog:
    async with Client(db_mcp.server) as client:
        result = await client.call_tool("get_catalog", {})
    return parse_tool_result(result, TypeAdapter(Catalog))
