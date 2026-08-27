from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from time import monotonic
from typing import cast

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AgentCapability
from pydantic_ai.messages import AgentStreamEvent, ModelMessage, RetryPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import RunUsage

from sql_agent.db_mcp import DbMcp
from sql_agent.exposure import ExposureMode, prepare_exposure
from sql_agent.history import HistoryPolicy, process_history_capability
from sql_agent.settings import Settings
from sql_agent.types import AgentAnswer, QueryResult

BASE_INSTRUCTIONS = """You answer natural-language questions using a read-only SQL database.
Use only the available schema and query tools; never guess table or column names.
Inspect the schema before writing PostgreSQL, execute the query, and base the answer
on returned rows.
If a tool reports rejection or failure, explain the safe failure without inventing data.
Finish with the required structured answer and concise evidence from tool results.
For a scalar row, include an evidence entry exactly in the form column=value.
"""


@dataclass(frozen=True)
class RequestDeps:
    request_id: str


@dataclass(frozen=True)
class AgentRun:
    answer: AgentAnswer
    mcp_calls: tuple[str, ...]
    query_results: tuple[QueryResult, ...]
    messages: tuple[ModelMessage, ...]
    latency_seconds: float
    first_event_seconds: float
    model_request_count: int
    input_tokens: int
    output_tokens: int
    retries: int


def build_agent(
    model: Model, *, history_policy: HistoryPolicy | None = None
) -> Agent[RequestDeps, AgentAnswer]:
    capabilities = (
        [cast(AgentCapability[RequestDeps], process_history_capability(history_policy))]
        if history_policy is not None
        else None
    )
    agent = Agent(
        model,
        output_type=AgentAnswer,
        deps_type=RequestDeps,
        instructions=BASE_INSTRUCTIONS,
        retries=2,
        name="schema_generic_sql_agent",
        capabilities=capabilities,
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


async def run_agent(
    agent: Agent[RequestDeps, AgentAnswer],
    prompt: str,
    db_mcp: DbMcp,
    mode: ExposureMode,
    deps: RequestDeps,
    *,
    message_history: tuple[ModelMessage, ...] = (),
    stream_events: bool = False,
    model_settings: OpenAIChatModelSettings | None = None,
    usage: RunUsage | None = None,
) -> AgentRun:
    started = monotonic()
    call_start = db_mcp.call_count()
    setup = await prepare_exposure(db_mcp, mode)
    first_event_at: list[float] = []

    async def observe_events(
        _ctx: RunContext[RequestDeps], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for _event in events:
            if not first_event_at:
                first_event_at.append(monotonic())

    result = await agent.run(
        prompt,
        deps=deps,
        instructions=setup.instructions,
        message_history=message_history,
        toolsets=[cast(AbstractToolset[RequestDeps], setup.toolset)],
        event_stream_handler=observe_events if stream_events else None,
        model_settings=model_settings,
        usage=usage,
    )
    finished = monotonic()
    messages = tuple(result.all_messages())
    calls = db_mcp.calls[call_start:]
    query_results = tuple(call.query_result for call in calls if call.query_result is not None)
    usage = result.usage
    retries = sum(
        isinstance(part, RetryPromptPart) for message in messages for part in message.parts
    )
    return AgentRun(
        answer=result.output,
        mcp_calls=tuple(call.tool_name for call in calls),
        query_results=query_results,
        messages=messages,
        latency_seconds=finished - started,
        first_event_seconds=(first_event_at[0] if first_event_at else finished) - started,
        model_request_count=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        retries=retries,
    )
