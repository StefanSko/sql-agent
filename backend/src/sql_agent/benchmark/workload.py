from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from sql_agent.types import AgentAnswer, JsonScalar, QueryOk, QueryResult, QueryTruncated

WORKLOAD_VERSION = "1"
_WORKLOAD_PATH = Path(__file__).parents[4] / "data" / "workloads" / "v1.json"


@dataclass(frozen=True)
class ExpectedScalar:
    column: str
    value: JsonScalar


@dataclass(frozen=True)
class WorkloadCase:
    case_id: str
    dataset: str
    prompt: str
    schema_path: str
    seed_directory: str | None
    expected: ExpectedScalar

    def oracle(self, query_results: tuple[QueryResult, ...], answer: AgentAnswer) -> bool:
        expected_evidence = f"{self.expected.column}={self.expected.value}"
        has_query_value = any(
            row.values.get(self.expected.column) == self.expected.value
            for result in query_results
            if isinstance(result, (QueryOk, QueryTruncated))
            for row in result.rows
        )
        return has_query_value and expected_evidence in answer.evidence


def load_workload(path: Path = _WORKLOAD_PATH) -> tuple[WorkloadCase, ...]:
    return tuple(TypeAdapter(list[WorkloadCase]).validate_json(path.read_bytes()))
