from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from sql_agent.agent import RequestDeps, build_database_agent
from sql_agent.mcp.server import create_database_server
from sql_agent.settings import Dsn
from tests.support.models import catalog_aggregation_model, catalog_model


def _tool_names(messages: list[list[ModelMessage]]) -> tuple[str, ...]:
    return tuple(
        part.tool_name
        for request in messages
        for message in request
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    )


async def test_prompt_crosses_agent_modern_mcp_and_database(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    server = create_database_server(seeded_dsn)
    agent = build_database_agent(catalog_model(seen), server)

    result = await agent.run(
        "What tables can I query?",
        deps=RequestDeps(request_id="acceptance"),
    )

    assert result.output.answer == "The database has three tables."
    assert _tool_names(seen) == ("run_query",)
    assert "<catalog>" in repr(seen)


async def test_nl_join_aggregation_asserts_database_result(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    server = create_database_server(seeded_dsn)
    agent = build_database_agent(catalog_aggregation_model(seen), server)

    result = await agent.run(
        "How many trips were taken by member riders?",
        deps=RequestDeps(request_id="aggregation"),
    )

    assert result.output.answer == "Member riders took 6 trips."
    assert "run_query" in _tool_names(seen)
    assert "member_trips" in repr(seen)
    assert "6" in repr(seen)


async def test_catalog_prefetch_failure_never_exposes_dsn() -> None:
    sentinel = "SENTINEL-DB-CREDENTIAL"
    server = create_database_server(Dsn(f"postgresql://{sentinel}:secret@127.0.0.1:1/postgres"))
    agent = build_database_agent(catalog_model(), server)

    with pytest.raises(Exception) as captured:
        await agent.run("Run a harmless query.", deps=RequestDeps(request_id="failure"))

    visible = str(captured.value)
    assert sentinel not in visible
    assert "postgresql://" not in visible
