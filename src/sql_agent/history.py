from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial

from pydantic_ai.capabilities.process_history import ProcessHistory
from pydantic_ai.messages import ModelMessage, ToolCallPart, ToolReturnPart


@dataclass(frozen=True)
class HistoryPolicy:
    keep_recent_tool_pairs: int

    def __post_init__(self) -> None:
        if self.keep_recent_tool_pairs < 0:
            raise ValueError("tool-pair retention cannot be negative")


def compact_tool_history(messages: list[ModelMessage], policy: HistoryPolicy) -> list[ModelMessage]:
    returned_ids = {
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    paired_ids = tuple(
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart) and part.tool_call_id in returned_ids
    )
    keep_ids = frozenset(
        paired_ids[-policy.keep_recent_tool_pairs :] if policy.keep_recent_tool_pairs else ()
    )
    compacted: list[ModelMessage] = []
    for message in messages:
        parts = tuple(
            part
            for part in message.parts
            if not (
                isinstance(part, (ToolCallPart, ToolReturnPart))
                and part.tool_call_id in returned_ids
                and part.tool_call_id not in keep_ids
            )
        )
        if parts:
            compacted.append(replace(message, parts=parts))
    return compacted


def process_history_capability(policy: HistoryPolicy) -> ProcessHistory[object]:
    return ProcessHistory(processor=partial(compact_tool_history, policy=policy))
