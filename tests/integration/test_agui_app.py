from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage

from sql_agent.app import create_app
from sql_agent.mcp.server import create_database_server
from sql_agent.settings import Dsn, Settings
from tests.support.models import FailingStreamModel, catalog_model


def settings(dsn: Dsn) -> Settings:
    return Settings(
        dsn=dsn,
        ollama_base_url="http://unused.invalid/v1",
        model_name="test-model",
        ollama_api_key=SecretStr("test-key"),
    )


def request(messages: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": messages or [{"id": "user-1", "role": "user", "content": "What tables exist?"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def events(response_text: str) -> Iterator[dict[str, object]]:
    for line in response_text.splitlines():
        if line.startswith("data: "):
            yield json.loads(line.removeprefix("data: "))


def test_agui_sequence_crosses_agent_mcp_and_pglite(seeded_dsn: Dsn) -> None:
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=catalog_model(),
    )

    with TestClient(app) as client:
        response = client.post("/agui", json=request(), headers={"x-request-id": "req-123"})

    assert response.status_code == 200
    event_types = [event["type"] for event in events(response.text)]
    assert event_types[0] == "RUN_STARTED"
    assert "TOOL_CALL_START" in event_types
    assert "TOOL_CALL_RESULT" in event_types
    assert "TEXT_MESSAGE_CONTENT" in event_types
    assert event_types[-1] == "RUN_FINISHED"


def test_agui_resends_full_history_and_passes_per_request_deps(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=catalog_model(seen),
    )
    history: list[dict[str, object]] = [
        {"id": "user-old", "role": "user", "content": "Earlier question"},
        {"id": "assistant-old", "role": "assistant", "content": "Earlier answer"},
        {"id": "user-new", "role": "user", "content": "What tables exist?"},
    ]

    with TestClient(app) as client:
        response = client.post(
            "/agui", json=request(history), headers={"x-request-id": "visible-request-id"}
        )

    assert response.status_code == 200
    serialized = repr(seen)
    assert "Earlier question" in serialized
    assert "Earlier answer" in serialized
    assert "visible-request-id" in serialized


def test_completion_bridge_ignores_matching_text_from_prior_turn(seeded_dsn: Dsn) -> None:
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=catalog_model(),
    )
    history: list[dict[str, object]] = [
        {"id": "user-old", "role": "user", "content": "What tables exist?"},
        {
            "id": "assistant-old",
            "role": "assistant",
            "content": "The database has three tables.",
        },
        {"id": "user-new", "role": "user", "content": "Check again."},
    ]

    with TestClient(app) as client:
        response = client.post("/agui", json=request(history))

    deltas = [
        str(event["delta"])
        for event in events(response.text)
        if event["type"] == "TEXT_MESSAGE_CONTENT"
    ]
    assert "The database has three tables." in "".join(deltas)


def test_agui_emits_protocol_error_after_midstream_failure(seeded_dsn: Dsn) -> None:
    failing = FailingStreamModel()
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=failing.as_model(),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/agui", json=request())

    assert response.status_code == 200
    event_types = [event["type"] for event in events(response.text)]
    assert "TEXT_MESSAGE_CONTENT" in event_types
    assert "RUN_ERROR" in event_types


def test_agui_reports_completed_usage_to_server_side_sink(seeded_dsn: Dsn) -> None:
    captured: list[RunUsage] = []
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=catalog_model(),
        usage_sink=captured.append,
    )

    with TestClient(app) as client:
        response = client.post("/agui", json=request())

    assert response.status_code == 200
    assert captured[0].requests == 2
    assert captured[0].input_tokens > 0


def test_static_ui_renders_text_and_tool_events(seeded_dsn: Dsn) -> None:
    app = create_app(
        settings=settings(seeded_dsn),
        database=create_database_server(seeded_dsn),
        model=catalog_model(),
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "TEXT_MESSAGE_CONTENT" in response.text
    assert "TOOL_CALL_START" in response.text
    assert "TOOL_CALL_RESULT" in response.text
    assert "toolCalls.find((call) => call.id === event.toolCallId)" in response.text
