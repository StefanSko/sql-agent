from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

ModelFunction = Callable[[list[ModelMessage], AgentInfo], ModelResponse]


def streaming_function_model(function: ModelFunction) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        response = function(messages, info)
        for index, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=json.dumps(part.args),
                        tool_call_id=part.tool_call_id,
                    )
                }

    return FunctionModel(function, stream_function=stream)


def _returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]


def _final(info: AgentInfo, answer: str, evidence: tuple[str, ...]) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {"answer": answer, "evidence": list(evidence)},
            )
        ]
    )


def list_tables_model(seen: list[list[ModelMessage]] | None = None) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        returns = _returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart("list_tables", {})])
        return _final(info, "The database has three tables.", ("list_tables",))

    return streaming_function_model(respond)


def catalog_model(seen: list[list[ModelMessage]] | None = None) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        assert {tool.name for tool in info.function_tools} == {"run_query"}
        assert "<catalog>" in repr(messages)
        returns = _returns(messages)
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_query",
                        {
                            "sql": "SELECT COUNT(*) AS table_count "
                            "FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                        },
                    )
                ]
            )
        return _final(info, "The database has three tables.", ("table_count=3",))

    return streaming_function_model(respond)


def catalog_aggregation_model(seen: list[list[ModelMessage]] | None = None) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        assert {tool.name for tool in info.function_tools} == {"run_query"}
        assert "<catalog>" in repr(messages)
        names = [part.tool_name for part in _returns(messages)]
        if "run_query" not in names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_query",
                        {
                            "sql": "SELECT COUNT(*) AS member_trips FROM trips "
                            "JOIN riders USING (rider_id) WHERE riders.plan = 'member'"
                        },
                    )
                ]
            )
        return _final(info, "Member riders took 6 trips.", ("member_trips=6",))

    return streaming_function_model(respond)


def aggregation_model(seen: list[list[ModelMessage]] | None = None) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(list(messages))
        names = [part.tool_name for part in _returns(messages)]
        if "list_tables" not in names:
            return ModelResponse(parts=[ToolCallPart("list_tables", {})])
        if "describe_table" not in names:
            return ModelResponse(
                parts=[
                    ToolCallPart("describe_table", {"name": "riders"}),
                    ToolCallPart("describe_table", {"name": "trips"}),
                ]
            )
        if "run_query" not in names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_query",
                        {
                            "sql": "SELECT COUNT(*) AS member_trips FROM trips "
                            "JOIN riders USING (rider_id) WHERE riders.plan = 'member'"
                        },
                    )
                ]
            )
        return _final(info, "Member riders took 6 trips.", ("member_trips=6",))

    return streaming_function_model(respond)


@dataclass
class FailingStreamModel:
    calls: int = field(default=0, init=False)

    def as_model(self) -> FunctionModel:
        async def stream(messages: list[ModelMessage], info: AgentInfo) -> Any:
            del messages, info
            self.calls += 1
            yield "partial"
            raise RuntimeError("deliberate stream failure")

        return FunctionModel(stream_function=stream)


def text_model(text: str) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(text)])

    return streaming_function_model(respond)
