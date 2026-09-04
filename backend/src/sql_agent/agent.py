from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastmcp import Client, FastMCP
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import AbstractToolset, FilteredToolset

from sql_agent.settings import Settings
from sql_agent.types import AgentAnswer

BASE_INSTRUCTIONS = """You answer natural-language questions using a read-only SQL database.
Call get_catalog before writing PostgreSQL, then use run_query and base the answer on its rows.
Never guess table or column names. If a query is rejected, explain the safe failure without
inventing data. Finish with the required structured answer and concise evidence from tool results.
For a scalar row, include an evidence entry exactly in the form column=value.
"""

_DATABASE_TOOLS = frozenset({"get_catalog", "run_query"})


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
