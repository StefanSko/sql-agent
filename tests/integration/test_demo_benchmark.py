from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.benchmark.demo import EvaluationFailed, ResultCorrect, ResultIncorrect, run_case
from sql_agent.benchmark.demo_workload import (
    Difficulty,
    EvaluationCase,
    GoldenCase,
    Ordering,
    Question,
    Split,
)
from sql_agent.benchmark.metrics import FailureKind
from sql_agent.settings import Dsn
from sql_agent.types import QueryOk, QueryRow
from tests.integration.test_agui_app import settings


def case() -> EvaluationCase:
    return EvaluationCase(
        Question(
            "test-case",
            Split.DEVELOPMENT,
            Difficulty.EASY,
            Ordering.ORDERED,
            "Count the stored journeys; return total.",
        ),
        "SELECT COUNT(*) AS total FROM trips -- SECRET_REFERENCE_SENTINEL",
        GoldenCase("test-case", "secret-hash", QueryOk((QueryRow({"total": 8}),))),
    )


@pytest.mark.parametrize("wrong_final_query", [False, True])
async def test_demo_grades_last_complete_result_without_leaking_gold(
    seeded_dsn: Dsn,
    wrong_final_query: bool,
) -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert "SECRET_REFERENCE_SENTINEL" not in repr(messages)
        assert "secret-hash" not in repr(messages)
        assert str(seeded_dsn) not in repr(messages)
        assert {tool.name for tool in info.function_tools} == {"run_query"}
        returns = [
            part for msg in messages for part in msg.parts if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(
                parts=[ToolCallPart("run_query", {"sql": "SELECT COUNT(*) AS total FROM trips"})]
            )
        if wrong_final_query and len(returns) == 1:
            return ModelResponse(parts=[ToolCallPart("run_query", {"sql": "SELECT 0 AS total"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answer": "Prose is deliberately not graded by this benchmark.",
                        "evidence": [],
                    },
                )
            ]
        )

    record = await run_case(
        FunctionModel(respond),
        settings(seeded_dsn),
        case(),
        repetition=0,
        seed=42,
        timeout_seconds=10,
    )
    expected_type = ResultIncorrect if wrong_final_query else ResultCorrect
    assert isinstance(record.outcome, expected_type)
    assert record.outcome.execution.queries[0].sql == "SELECT COUNT(*) AS total FROM trips"
    assert record.outcome.execution.model_request_count >= 2


async def test_demo_records_timeout_instead_of_dropping_attempt(seeded_dsn: Dsn) -> None:
    async def delayed(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        await asyncio.sleep(10)
        return ModelResponse(parts=[])

    record = await run_case(
        FunctionModel(delayed),
        settings(seeded_dsn),
        case(),
        repetition=0,
        seed=42,
        timeout_seconds=0.05,
    )
    assert isinstance(record.outcome, EvaluationFailed)
    assert record.outcome.failure is FailureKind.TIMEOUT
