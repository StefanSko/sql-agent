from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class BaselineToolCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class BaselineText:
    text: str


@dataclass(frozen=True)
class BaselineToolCalls:
    calls: tuple[BaselineToolCall, ...]


type BaselineTurn = BaselineText | BaselineToolCalls


class BaselineModel(Protocol):
    async def complete(
        self,
        messages: tuple[dict[str, object], ...],
        tools: tuple[dict[str, object], ...],
    ) -> BaselineTurn: ...


class BaselineBackend(Protocol):
    async def tool_definitions(self) -> tuple[dict[str, object], ...]: ...

    async def call(self, name: str, arguments: dict[str, object]) -> str: ...


@dataclass(frozen=True)
class BaselineToolCallEvent:
    tool_call_id: str
    content: str
    kind: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class BaselineToolResultEvent:
    tool_call_id: str
    content: str
    kind: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class BaselineTextEvent:
    content: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True)
class BaselineDoneEvent:
    content: str = ""
    kind: Literal["done"] = "done"


@dataclass(frozen=True)
class BaselineErrorEvent:
    content: str
    kind: Literal["error"] = "error"


type BaselineEvent = (
    BaselineToolCallEvent
    | BaselineToolResultEvent
    | BaselineTextEvent
    | BaselineDoneEvent
    | BaselineErrorEvent
)


async def run_loop(
    prompt: str,
    model: BaselineModel,
    backend: BaselineBackend,
    *,
    max_model_requests: int = 8,
) -> AsyncIterator[BaselineEvent]:
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "Use the database tools to inspect the schema, execute one read-only query when "
                "needed, and answer only from returned data. Never guess schema names."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    tools = await backend.tool_definitions()
    for _request in range(max_model_requests):
        turn = await model.complete(tuple(messages), tools)
        match turn:
            case BaselineText(text=text):
                yield BaselineTextEvent(content=text)
                yield BaselineDoneEvent()
                return
            case BaselineToolCalls(calls=calls):
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call.call_id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments, separators=(",", ":")),
                                },
                            }
                            for call in calls
                        ],
                    }
                )
                for call in calls:
                    yield BaselineToolCallEvent(tool_call_id=call.call_id, content=call.name)
                    result = await backend.call(call.name, call.arguments)
                    yield BaselineToolResultEvent(tool_call_id=call.call_id, content=result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "name": call.name,
                            "content": result,
                        }
                    )
    yield BaselineErrorEvent(content="model request limit reached")
