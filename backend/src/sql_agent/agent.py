from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastmcp import Client, FastMCP
from pydantic import TypeAdapter
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import AbstractToolset, FilteredToolset

from sql_agent.mcp.client import fetch_catalog
from sql_agent.settings import Settings
from sql_agent.types import AgentAnswer, Catalog

BASE_INSTRUCTIONS = """You answer natural-language questions using a read-only SQL database.
Use schema information supplied in the instructions or available schema tools before writing
PostgreSQL, then call run_query and base the answer on its rows. Never guess table or column names.
If a query is rejected, explain the safe failure without inventing data. Finish with the required
structured answer and concise evidence from tool results. For a scalar row, include an evidence
entry exactly in the form column=value.
"""

_DATABASE_TOOLS = frozenset({"run_query"})
_CATALOG = TypeAdapter(Catalog)


@dataclass(frozen=True)
class RequestDeps:
    request_id: str


def database_toolset(server: FastMCP) -> AbstractToolset[RequestDeps]:
    """Expose the application's fixed database-tool surface over modern MCP."""
    mcp = MCPToolset(
        Client(server, mode="auto"),
        tool_error_behavior="failed",
        prefer_tasks=False,
    )
    filtered = FilteredToolset(mcp, lambda _ctx, tool: tool.name in _DATABASE_TOOLS)
    return cast(AbstractToolset[RequestDeps], filtered)


def build_database_agent(model: Model, server: FastMCP) -> Agent[RequestDeps, AgentAnswer]:
    agent = build_agent(model, database_toolset(server))

    @agent.instructions
    async def catalog_instruction(_ctx: RunContext[RequestDeps]) -> str:
        catalog = await fetch_catalog(server)
        encoded = _CATALOG.dump_json(catalog).decode("utf-8")
        return (
            "The catalog below was prefetched through MCP for this run. Use it to write SQL.\n"
            f"<catalog>{encoded}</catalog>"
        )

    return agent


def build_agent(
    model: Model, toolset: AbstractToolset[RequestDeps]
) -> Agent[RequestDeps, AgentAnswer]:
    agent = Agent(
        model,
        output_type=AgentAnswer,
        deps_type=RequestDeps,
        instructions=BASE_INSTRUCTIONS,
        retries=2,
        name="schema_generic_sql_agent",
        toolsets=[toolset],
    )

    @agent.instructions
    def request_instruction(ctx: RunContext[RequestDeps]) -> str:
        return f"Request correlation ID: {ctx.deps.request_id}"

    return agent


def ollama_model(settings: Settings) -> OpenAIChatModel:
    provider = OpenAIProvider(
        base_url=str(settings.ollama_base_url),
        api_key=settings.ollama_api_key.get_secret_value(),
    )
    return OpenAIChatModel(settings.model_name, provider=provider)
