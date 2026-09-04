from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from fastmcp import Client, FastMCP
from pydantic import TypeAdapter
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset, ToolResult
from pydantic_ai.toolsets import AbstractToolset, FilteredToolset

from sql_agent.agent import RequestDeps
from sql_agent.benchmark.mcp_result import parse_tool_result
from sql_agent.benchmark.types import ExposureMode
from sql_agent.types import Catalog, QueryResult

_QUERY_RESULT = TypeAdapter(QueryResult)


@dataclass(frozen=True)
class BenchmarkCall:
    tool_name: str
    query_result: QueryResult | None = None


@dataclass
class BenchmarkTrace:
    """Mutable trace scoped to one benchmark run."""

    calls: list[BenchmarkCall] = field(default_factory=list)

    async def call_tool(
        self,
        _ctx: RunContext[object],
        call_tool: CallToolFunc,
        name: str,
        args: dict[str, object],
    ) -> ToolResult:
        result = await call_tool(name, args)
        query_result = _parse_query_result(result) if name == "run_query" else None
        self.calls.append(BenchmarkCall(tool_name=name, query_result=query_result))
        return result


@dataclass(frozen=True)
class ExposureSetup:
    toolset: AbstractToolset[RequestDeps]
    instructions: str
    trace: BenchmarkTrace


async def prepare_exposure(server: FastMCP, mode: ExposureMode) -> ExposureSetup:
    trace = BenchmarkTrace()
    mcp = MCPToolset(
        Client(server, mode="auto"),
        tool_error_behavior="failed",
        prefer_tasks=False,
        process_tool_call=trace.call_tool,
    )
    match mode:
        case ExposureMode.GRANULAR:
            included = frozenset({"list_tables", "describe_table", "run_query"})
            instructions = "Discover the schema with the available tools before writing SQL."
        case ExposureMode.CATALOG:
            included = frozenset({"get_catalog", "run_query"})
            instructions = "Retrieve the catalog with the available tool before writing SQL."
        case ExposureMode.PREFETCHED:
            included = frozenset({"run_query"})
            catalog = await _prefetch_catalog(server)
            trace.calls.append(BenchmarkCall(tool_name="get_catalog"))
            encoded = TypeAdapter(Catalog).dump_json(catalog).decode("utf-8")
            instructions = (
                "The catalog below was fetched through MCP for this run. Use it to write SQL.\n"
                f"<catalog>{encoded}</catalog>"
            )
    filtered = FilteredToolset(mcp, lambda _ctx, tool: tool.name in included)
    return ExposureSetup(
        toolset=cast(AbstractToolset[RequestDeps], filtered),
        instructions=instructions,
        trace=trace,
    )


async def _prefetch_catalog(server: FastMCP) -> Catalog:
    async with Client(server, mode="auto") as client:
        result = await client.call_tool("get_catalog", {})
    return parse_tool_result(result, TypeAdapter(Catalog))


def _parse_query_result(result: ToolResult) -> QueryResult:
    if isinstance(result, dict) and set(result) == {"result"}:
        result = result["result"]
    return _QUERY_RESULT.validate_python(result)
