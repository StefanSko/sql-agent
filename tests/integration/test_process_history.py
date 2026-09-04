from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.agent import RequestDeps, build_agent, run_agent
from sql_agent.history import HistoryPolicy
from sql_agent.mcp.server import create_db_mcp
from sql_agent.settings import Dsn
from sql_agent.types import ExposureMode


def tool_pair(index: int) -> tuple[ModelMessage, ModelMessage]:
    call_id = f"old-{index}"
    return (
        ModelResponse(parts=[ToolCallPart("run_query", {"sql": "SELECT 1"}, call_id)]),
        ModelRequest(parts=[ToolReturnPart("run_query", {"value": index}, call_id)]),
    )


async def test_agent_exercises_process_history_capability(seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(list(messages))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answer": "Compacted.", "evidence": ["history"]},
                )
            ]
        )

    agent = build_agent(
        FunctionModel(respond), history_policy=HistoryPolicy(keep_recent_tool_pairs=1)
    )
    history = tool_pair(1) + tool_pair(2) + tool_pair(3)

    await run_agent(
        agent,
        "Continue.",
        create_db_mcp(seeded_dsn),
        ExposureMode.GRANULAR,
        RequestDeps(request_id="history"),
        message_history=history,
    )

    visible = repr(seen[0])
    assert "old-1" not in visible
    assert "old-2" not in visible
    assert "old-3" in visible
