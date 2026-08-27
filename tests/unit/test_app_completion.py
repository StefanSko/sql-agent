from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from sql_agent.app import should_bridge_answer


def test_structured_answer_is_not_bridged_when_model_already_streamed_it() -> None:
    messages = (
        ModelResponse(
            parts=[
                TextPart("There were 6 records."),
                ToolCallPart(
                    "final_result",
                    {"answer": "There were 6 records.", "evidence": ["count=6"]},
                ),
            ]
        ),
    )

    assert should_bridge_answer(messages, "There were 6 records.") is False


def test_answer_split_across_text_parts_is_not_bridged_twice() -> None:
    messages = (
        ModelResponse(parts=[TextPart("There were 6 records."), TextPart(" Evidence: count=6")]),
    )

    assert should_bridge_answer(messages, "There were 6 records. Evidence: count=6") is False


def test_provisional_text_containing_scalar_answer_does_not_suppress_final() -> None:
    messages = (ModelResponse(parts=[TextPart("6 is possible; still checking.")]),)

    assert should_bridge_answer(messages, "6") is True


def test_output_tool_only_answer_is_bridged_to_visible_text() -> None:
    messages = (
        ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"answer": "There were 6 records.", "evidence": ["count=6"]},
                )
            ]
        ),
    )

    assert should_bridge_answer(messages, "There were 6 records.") is True
