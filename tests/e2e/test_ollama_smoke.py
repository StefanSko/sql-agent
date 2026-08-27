from __future__ import annotations

import os

import pytest

from sql_agent.agent import RequestDeps, build_agent, ollama_model, run_agent
from sql_agent.db_mcp import create_db_mcp
from sql_agent.exposure import ExposureMode
from sql_agent.settings import Dsn, Settings
from sql_agent.types import QueryOk

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def require_local_e2e() -> None:
    if os.environ.get("SQL_AGENT_RUN_LOCAL_E2E") != "1":
        pytest.skip("set SQL_AGENT_RUN_LOCAL_E2E=1 to run local Ollama tests")


async def test_real_ollama_lists_tables_through_mcp_and_pglite(seeded_dsn: Dsn) -> None:
    settings = Settings.from_env()
    db_mcp = create_db_mcp(seeded_dsn)

    result = await run_agent(
        build_agent(ollama_model(settings)),
        "Inspect the database tools and tell me only how many queryable tables exist.",
        db_mcp,
        ExposureMode.GRANULAR,
        RequestDeps(request_id="ollama-m1"),
    )

    assert "list_tables" in result.mcp_calls
    assert "3" in result.answer.answer


async def test_real_ollama_executes_safe_join_aggregation(seeded_dsn: Dsn) -> None:
    settings = Settings.from_env()
    db_mcp = create_db_mcp(seeded_dsn)

    result = await run_agent(
        build_agent(ollama_model(settings)),
        "How many trips were taken by member riders? Use the database tools and report the number.",
        db_mcp,
        ExposureMode.GRANULAR,
        RequestDeps(request_id="ollama-m2"),
    )

    query = result.query_results[-1]
    assert isinstance(query, QueryOk)
    assert tuple(query.rows[0].values.values()) == (6,)
    assert "6" in result.answer.answer
