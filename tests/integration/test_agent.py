from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.agent import RequestDeps, build_agent, run_agent
from sql_agent.mcp.server import create_db_mcp
from sql_agent.settings import Dsn
from sql_agent.types import ExposureMode, QueryOk, QueryRejected
from tests.support.models import aggregation_model, list_tables_model


async def test_prompt_crosses_agent_mcp_and_database(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    db_mcp = create_db_mcp(seeded_dsn)
    agent = build_agent(list_tables_model(seen))

    result = await run_agent(
        agent,
        "What tables can I query?",
        db_mcp,
        ExposureMode.GRANULAR,
        RequestDeps(request_id="acceptance-m1"),
    )

    assert result.answer.answer == "The database has three tables."
    assert result.mcp_calls == ("list_tables",)
    assert seen


async def test_nl_join_aggregation_asserts_database_result(seeded_dsn: Dsn) -> None:
    db_mcp = create_db_mcp(seeded_dsn)
    agent = build_agent(aggregation_model())

    result = await run_agent(
        agent,
        "How many trips were taken by member riders?",
        db_mcp,
        ExposureMode.GRANULAR,
        RequestDeps(request_id="acceptance-m2"),
    )

    assert result.answer.answer == "Member riders took 6 trips."
    assert result.mcp_calls == (
        "list_tables",
        "describe_table",
        "describe_table",
        "run_query",
    )
    query_result = result.query_results[-1]
    assert isinstance(query_result, QueryOk)
    assert query_result.rows[0].values == {"member_trips": 6}


async def test_database_failure_and_history_never_expose_dsn(seeded_dsn: Dsn) -> None:
    sentinel = "SENTINEL-DB-CREDENTIAL"
    dsn_with_sentinel = Dsn(f"postgresql://{sentinel}:secret@127.0.0.1:1/postgres")
    seen: list[list[ModelMessage]] = []
    db_mcp = create_db_mcp(dsn_with_sentinel)

    def failing_model() -> FunctionModel:
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

        return FunctionModel(respond)

    agent = build_agent(failing_model())
    result = await run_agent(
        agent,
        "Run a harmless query.",
        db_mcp,
        ExposureMode.GRANULAR,
        RequestDeps(request_id="failure"),
    )

    assert result.query_results[0] == QueryRejected(reason="database unavailable")
    visible = f"{seen!r}\n{result!r}"
    assert sentinel not in visible
    assert "postgresql://" not in visible


async def test_prefetch_failure_masks_dsn_before_model_run() -> None:
    sentinel = "SENTINEL-PREFETCH-CREDENTIAL"
    db_mcp = create_db_mcp(Dsn(f"postgresql://{sentinel}:secret@127.0.0.1:1/postgres"))

    with pytest.raises(Exception) as captured:
        await run_agent(
            build_agent(aggregation_model()),
            "Use the database.",
            db_mcp,
            ExposureMode.PREFETCHED,
            RequestDeps(request_id="prefetch-failure"),
        )

    visible = str(captured.value)
    assert sentinel not in visible
    assert "postgresql://" not in visible
