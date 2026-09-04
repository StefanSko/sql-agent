from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.agent import RequestDeps, build_agent, run_agent
from sql_agent.db_mcp import create_db_mcp
from sql_agent.exposure import ExposureMode
from sql_agent.settings import Dsn
from tests.support.pglite import load_dataset

ROOT = Path(__file__).parents[2]


def model_for_mode(mode: ExposureMode) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        returned_names = [part.tool_name for part in returns]
        tool_names = {tool.name for tool in info.function_tools}
        if mode is ExposureMode.GRANULAR and "list_tables" not in returned_names:
            return ModelResponse(parts=[ToolCallPart("list_tables", {})])
        if mode is ExposureMode.GRANULAR and "describe_table" not in returned_names:
            return ModelResponse(parts=[ToolCallPart("describe_table", {"name": "artifacts"})])
        if mode is ExposureMode.CATALOG and "get_catalog" not in returned_names:
            return ModelResponse(parts=[ToolCallPart("get_catalog", {})])
        if "run_query" not in returned_names:
            assert tool_names >= {"run_query"}
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_query", {"sql": "SELECT SUM(quantity) AS total FROM artifacts"}
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answer": "There are 23 items.", "evidence": ["total=23"]},
                )
            ]
        )

    return FunctionModel(respond)


async def test_all_exposure_modes_are_schema_generic_on_held_out_database(pglite_dsn: Dsn) -> None:
    await load_dataset(pglite_dsn, ROOT / "tests" / "data" / "heldout.sql", None)

    expected_calls = {
        ExposureMode.GRANULAR: ("list_tables", "describe_table", "run_query"),
        ExposureMode.CATALOG: ("get_catalog", "run_query"),
        ExposureMode.PREFETCHED: ("get_catalog", "run_query"),
    }
    for mode in ExposureMode:
        db_mcp = create_db_mcp(pglite_dsn)
        result = await run_agent(
            build_agent(model_for_mode(mode)),
            "What is the total quantity?",
            db_mcp,
            mode,
            RequestDeps(request_id=f"heldout-{mode.value}"),
        )
        assert result.answer.answer == "There are 23 items."
        assert result.mcp_calls == expected_calls[mode]


def test_production_prompts_and_tool_descriptions_are_schema_generic() -> None:
    production = Path("backend/src/sql_agent")
    forbidden = ("bike", "stations", "riders", "trips", "artifacts")
    for path in production.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for name in forbidden:
            assert name not in text, f"{path} contains dataset-specific name {name!r}"
