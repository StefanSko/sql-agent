from __future__ import annotations

from sql_agent.multiturn_experiment import apply_agui_events


def test_agui_event_history_preserves_tool_pair_continuity() -> None:
    messages: list[dict[str, object]] = []
    apply_agui_events(
        messages,
        (
            {
                "type": "TOOL_CALL_START",
                "toolCallId": "call-1",
                "toolCallName": "run_query",
                "parentMessageId": "assistant-1",
            },
            {"type": "TOOL_CALL_ARGS", "toolCallId": "call-1", "delta": '{"sql":"SELECT 1"}'},
            {
                "type": "REASONING_ENCRYPTED_VALUE",
                "subtype": "tool-call",
                "entityId": "call-1",
                "encryptedValue": "kind-value",
            },
            {
                "type": "TOOL_CALL_RESULT",
                "messageId": "tool-1",
                "toolCallId": "call-1",
                "content": '{"value":1}',
            },
            {
                "type": "REASONING_ENCRYPTED_VALUE",
                "subtype": "message",
                "entityId": "tool-1",
                "encryptedValue": "outcome-value",
            },
        ),
    )

    assistant = messages[0]
    raw_calls = assistant["toolCalls"]
    assert isinstance(raw_calls, list)
    call = raw_calls[0]
    assert isinstance(call, dict)
    assert call["encryptedValue"] == "kind-value"
    assert messages[1]["encryptedValue"] == "outcome-value"


def test_tool_call_attaches_to_an_existing_assistant_message() -> None:
    messages: list[dict[str, object]] = []
    apply_agui_events(
        messages,
        (
            {"type": "TEXT_MESSAGE_START", "messageId": "assistant-1"},
            {
                "type": "TOOL_CALL_START",
                "toolCallId": "call-1",
                "toolCallName": "run_query",
                "parentMessageId": "assistant-1",
            },
            {
                "type": "TOOL_CALL_RESULT",
                "messageId": "tool-1",
                "toolCallId": "call-1",
                "content": "ok",
            },
        ),
    )

    assert messages[0]["toolCalls"] != []
