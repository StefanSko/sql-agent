from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.agent import RequestDeps, build_agent, database_toolset
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
    agent = build_agent(catalog_model(seen), database_toolset(server))

    result = await agent.run(
        "What tables can I query?",
        deps=RequestDeps(request_id="acceptance"),
    )

    assert result.output.answer == "The database has three tables."
    assert "get_catalog" in _tool_names(seen)


async def test_nl_join_aggregation_asserts_database_result(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    server = create_database_server(seeded_dsn)
    agent = build_agent(catalog_aggregation_model(seen), database_toolset(server))

    result = await agent.run(
        "How many trips were taken by member riders?",
        deps=RequestDeps(request_id="aggregation"),
    )

    assert result.output.answer == "Member riders took 6 trips."
    assert "run_query" in _tool_names(seen)
    assert "member_trips" in repr(seen)
    assert "6" in repr(seen)


async def test_database_failure_and_history_never_expose_dsn() -> None:
    sentinel = "SENTINEL-DB-CREDENTIAL"
    server = create_database_server(Dsn(f"postgresql://{sentinel}:secret@127.0.0.1:1/postgres"))
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(list(messages))
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("run_query", {"sql": "SELECT 1"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answer": "The query failed safely.", "evidence": ["connection failure"]},
                )
            ]
        )

    agent = build_agent(FunctionModel(respond), database_toolset(server))
    result = await agent.run("Run a harmless query.", deps=RequestDeps(request_id="failure"))

    visible = f"{seen!r}\n{result!r}"
    assert result.output.answer == "The query failed safely."
    assert "database unavailable" in visible
    assert sentinel not in visible
    assert "postgresql://" not in visible
