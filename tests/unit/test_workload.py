from __future__ import annotations

from sql_agent.types import AgentAnswer, QueryOk, QueryRow
from sql_agent.workload import WORKLOAD_VERSION, load_workload


def test_versioned_workload_uses_deterministic_typed_oracles() -> None:
    workload = load_workload()

    assert WORKLOAD_VERSION == "1"
    assert len(workload) >= 2
    for case in workload:
        matching = QueryOk(
            rows=(QueryRow.from_mapping({case.expected.column: case.expected.value}),)
        )
        answer = AgentAnswer(
            answer=f"The result is {case.expected.value}.",
            evidence=(f"{case.expected.column}={case.expected.value}",),
        )
        assert case.oracle((matching,), answer) is True
        assert case.oracle((), answer) is False
