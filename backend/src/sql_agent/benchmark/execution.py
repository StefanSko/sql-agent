from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from time import monotonic

from fastmcp import FastMCP
from pydantic_ai import RunContext
from pydantic_ai.messages import AgentStreamEvent, ModelMessage, RetryPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings

from sql_agent.agent import RequestDeps, build_agent
from sql_agent.benchmark.exposure import prepare_exposure
from sql_agent.benchmark.types import ExposureMode
from sql_agent.types import AgentAnswer, QueryResult


@dataclass(frozen=True)
class BenchmarkRun:
    answer: AgentAnswer
    mcp_calls: tuple[str, ...]
    query_results: tuple[QueryResult, ...]
    latency_seconds: float
    first_event_seconds: float
    model_request_count: int
    input_tokens: int
    output_tokens: int
    retries: int


async def run_agent(
    model: Model,
    prompt: str,
    server: FastMCP,
    mode: ExposureMode,
    deps: RequestDeps,
    *,
    stream_events: bool = False,
    model_settings: OpenAIChatModelSettings | None = None,
) -> BenchmarkRun:
    started = monotonic()
    setup = await prepare_exposure(server, mode)
    first_event_at: list[float] = []

    async def observe_events(
        _ctx: RunContext[RequestDeps], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for _event in events:
            if not first_event_at:
                first_event_at.append(monotonic())

    result = await build_agent(model, setup.toolset).run(
        prompt,
        deps=deps,
        instructions=setup.instructions,
        event_stream_handler=observe_events if stream_events else None,
        model_settings=model_settings,
    )
    finished = monotonic()
    messages: tuple[ModelMessage, ...] = tuple(result.all_messages())
    usage = result.usage
    calls = tuple(setup.trace.calls)
    return BenchmarkRun(
        answer=result.output,
        mcp_calls=tuple(call.tool_name for call in calls),
        query_results=tuple(call.query_result for call in calls if call.query_result is not None),
        latency_seconds=finished - started,
        first_event_seconds=(first_event_at[0] if first_event_at else finished) - started,
        model_request_count=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        retries=sum(
            isinstance(part, RetryPromptPart) for message in messages for part in message.parts
        ),
    )
