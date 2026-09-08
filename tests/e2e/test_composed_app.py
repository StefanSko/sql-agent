from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _events(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _answer(events: list[dict[str, object]]) -> str:
    return "".join(
        str(event.get("delta", ""))
        for event in events
        if event.get("type") == "TEXT_MESSAGE_CONTENT"
    )


def _append_frontend_history(
    messages: list[dict[str, Any]], events: list[dict[str, object]]
) -> None:
    calls: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event.get("type")
        if event_type == "TEXT_MESSAGE_START":
            messages.append({"id": event["messageId"], "role": "assistant", "content": ""})
        elif event_type == "TEXT_MESSAGE_CONTENT":
            message = next(item for item in messages if item["id"] == event["messageId"])
            message["content"] += event["delta"]
        elif event_type == "TOOL_CALL_START":
            call_id = str(event["toolCallId"])
            parent_id = event.get("parentMessageId") or f"assistant-{call_id}"
            owner = next((item for item in messages if item["id"] == parent_id), None)
            if owner is None:
                owner = {
                    "id": parent_id,
                    "role": "assistant",
                    "content": None,
                    "toolCalls": [],
                }
                messages.append(owner)
            call = {
                "id": call_id,
                "type": "function",
                "function": {"name": event["toolCallName"], "arguments": ""},
            }
            tool_calls = owner["toolCalls"]
            assert isinstance(tool_calls, list)
            tool_calls.append(call)
            calls[call_id] = call
        elif event_type == "TOOL_CALL_ARGS":
            call = calls[str(event["toolCallId"])]
            call["function"]["arguments"] += event["delta"]
        elif event_type == "TOOL_CALL_RESULT":
            messages.append(
                {
                    "id": event["messageId"],
                    "role": "tool",
                    "content": event["content"],
                    "toolCallId": event["toolCallId"],
                }
            )


def test_composed_app_serves_real_nl_sql_journey() -> None:
    base_url = os.environ.get("SQL_AGENT_COMPOSED_URL")
    if base_url is None:
        pytest.skip("set SQL_AGENT_COMPOSED_URL after starting the compose stack")
    payload = {
        "threadId": "compose-e2e",
        "runId": "compose-run-1",
        "state": {},
        "messages": [
            {
                "id": "compose-user-1",
                "role": "user",
                "content": "How many trips were taken by member riders? Use database tools.",
            }
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = httpx.post(f"{base_url.rstrip('/')}/agui", json=payload, timeout=180)

    response.raise_for_status()
    events = _events(response)
    assert "6" in _answer(events)
    assert sum(event.get("type") == "TEXT_MESSAGE_START" for event in events) == 1
    assert any(event.get("type") == "TOOL_CALL_RESULT" for event in events)
    assert not any(event.get("type") == "RUN_ERROR" for event in events)


def test_composed_app_follow_up_emits_one_clean_answer() -> None:
    base_url = os.environ.get("SQL_AGENT_COMPOSED_URL")
    if base_url is None:
        pytest.skip("set SQL_AGENT_COMPOSED_URL after starting the compose stack")
    messages: list[dict[str, Any]] = [
        {"id": "quality-user-1", "role": "user", "content": "How many rides are there?"}
    ]
    first = httpx.post(
        f"{base_url.rstrip('/')}/agui",
        json={
            "threadId": "quality-thread",
            "runId": "quality-run-1",
            "state": {},
            "messages": messages,
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        timeout=180,
    )
    first.raise_for_status()
    first_events = _events(first)
    first_answer = _answer(first_events)
    _append_frontend_history(messages, first_events)
    messages.append(
        {
            "id": "quality-user-2",
            "role": "user",
            "content": "Find something interesting about those.",
        }
    )

    second = httpx.post(
        f"{base_url.rstrip('/')}/agui",
        json={
            "threadId": "quality-thread",
            "runId": "quality-run-2",
            "state": {},
            "messages": messages,
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        timeout=180,
    )

    second.raise_for_status()
    second_events = _events(second)
    answer = _answer(second_events)
    assert first_answer
    assert answer
    assert sum(event.get("type") == "TEXT_MESSAGE_START" for event in second_events) == 1
    assert "evidence:" not in answer.lower()
    assert "found_evidence" not in answer.lower()
    assert not any(event.get("type") == "RUN_ERROR" for event in second_events)
