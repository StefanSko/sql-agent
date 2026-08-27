from __future__ import annotations

import json
import os

import httpx
import pytest

pytestmark = pytest.mark.e2e


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
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert "6" in "".join(
        event.get("delta", "") for event in events if event.get("type") == "TEXT_MESSAGE_CONTENT"
    )
    assert any(event.get("type") == "TOOL_CALL_RESULT" for event in events)
    assert not any(event.get("type") == "RUN_ERROR" for event in events)
