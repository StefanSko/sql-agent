from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from sql_agent.history import HistoryPolicy, compact_tool_history
from sql_agent.multiturn import MultiTurnMeasurement, ResendAssessment, assess_full_resend


def pair(index: int) -> list[ModelMessage]:
    call_id = f"call-{index}"
    return [
        ModelResponse(parts=[ToolCallPart("run_query", {"sql": "SELECT 1"}, call_id)]),
        ModelRequest(parts=[ToolReturnPart("run_query", {"value": index}, call_id)]),
    ]


def test_history_processor_is_immutable_and_keeps_valid_tool_pairs() -> None:
    original: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("question")])]
    original.extend(pair(1))
    original.extend(pair(2))
    original.extend(pair(3))
    original.append(ModelResponse(parts=[TextPart("answer")]))
    snapshot = repr(original)

    compacted = compact_tool_history(original, HistoryPolicy(keep_recent_tool_pairs=1))

    assert repr(original) == snapshot
    assert compacted is not original
    call_ids = {
        part.tool_call_id
        for message in compacted
        for part in message.parts
        if isinstance(part, (ToolCallPart, ToolReturnPart))
    }
    assert call_ids == {"call-3"}
    assert any(isinstance(part, UserPromptPart) for message in compacted for part in message.parts)
    assert any(isinstance(part, TextPart) for message in compacted for part in message.parts)


def test_full_resend_acceptance_thresholds_are_explicit() -> None:
    measurements = (
        MultiTurnMeasurement(
            turn=1,
            request_bytes=100,
            input_tokens=100,
            latency_seconds=1.0,
            correct=True,
            context_limit=1_000,
        ),
        MultiTurnMeasurement(
            turn=5,
            request_bytes=500,
            input_tokens=200,
            latency_seconds=1.5,
            correct=True,
            context_limit=1_000,
        ),
        MultiTurnMeasurement(
            turn=10,
            request_bytes=1_000,
            input_tokens=240,
            latency_seconds=2.0,
            correct=True,
            context_limit=1_000,
        ),
    )

    assert assess_full_resend(measurements) is ResendAssessment.ACCEPTABLE

    too_many_tokens = (
        *measurements[:-1],
        MultiTurnMeasurement(
            turn=10,
            request_bytes=1_000,
            input_tokens=250,
            latency_seconds=2.0,
            correct=True,
            context_limit=1_000,
        ),
    )
    assert assess_full_resend(too_many_tokens) is ResendAssessment.UNACCEPTABLE
