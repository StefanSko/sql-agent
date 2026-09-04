from __future__ import annotations

import os

import pytest

from sql_agent.agent import RequestDeps, build_agent, database_toolset, ollama_model
from sql_agent.mcp.server import create_database_server
from sql_agent.settings import Dsn, Settings

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def require_local_e2e() -> None:
    if os.environ.get("SQL_AGENT_RUN_LOCAL_E2E") != "1":
        pytest.skip("set SQL_AGENT_RUN_LOCAL_E2E=1 to run local Ollama tests")


async def test_real_ollama_executes_safe_join_aggregation(seeded_dsn: Dsn) -> None:
    settings = Settings.from_env()
    database = create_database_server(seeded_dsn)
    agent = build_agent(ollama_model(settings), database_toolset(database))

    result = await agent.run(
        "How many trips were taken by member riders? Use the database tools and report the number.",
        deps=RequestDeps(request_id="ollama-smoke"),
    )

    assert "6" in result.output.answer
    assert "member_trips=6" in result.output.evidence
