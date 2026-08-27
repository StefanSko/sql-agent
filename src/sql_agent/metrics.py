from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import median
from typing import Literal

from pydantic import TypeAdapter

from sql_agent.types import ExposureMode


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    INCOMPLETE_METRICS = "incomplete_metrics"
    RETRY_EXHAUSTED = "retry_exhausted"
    WRONG_RESULT = "wrong_result"
    EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True)
class CompleteMetrics:
    latency_seconds: float
    first_event_seconds: float
    model_request_count: int
    input_tokens: int
    output_tokens: int
    retries: int
    mcp_calls: tuple[str, ...]

    def __post_init__(self) -> None:
        numeric = (
            self.latency_seconds,
            self.first_event_seconds,
            self.model_request_count,
            self.input_tokens,
            self.output_tokens,
            self.retries,
        )
        if any(value < 0 for value in numeric):
            raise ValueError("complete metrics cannot contain negative values")
        if self.first_event_seconds > self.latency_seconds:
            raise ValueError("first event cannot occur after completion")


@dataclass(frozen=True)
class RunSucceeded:
    metrics: CompleteMetrics
    kind: Literal["succeeded"] = field(default="succeeded", init=False)


@dataclass(frozen=True)
class RunFailed:
    kind: FailureKind
    detail: str
    metrics: CompleteMetrics | None = None
    outcome: Literal["failed"] = field(default="failed", init=False)


RunOutcome = RunSucceeded | RunFailed


@dataclass(frozen=True)
class RunRecord:
    workload_version: str
    mode: ExposureMode
    case_id: str
    repetition: int
    run_order: int
    seed: int | None
    outcome: RunOutcome


@dataclass(frozen=True)
class VariantChecks:
    mode: ExposureMode
    safety_passed: bool
    heldout_schema_passed: bool


@dataclass(frozen=True)
class ExperimentChecks:
    variants: tuple[VariantChecks, ...]

    def for_mode(self, mode: ExposureMode) -> VariantChecks | None:
        return next((check for check in self.variants if check.mode is mode), None)


@dataclass(frozen=True)
class VariantScore:
    correct_repetitions: int
    macro_median_model_requests: float | None
    macro_median_latency_seconds: float | None
    macro_median_input_tokens: float | None

    @property
    def ranking_key(self) -> tuple[float, float, float, float]:
        return (
            -float(self.correct_repetitions),
            _rank_metric(self.macro_median_model_requests),
            _rank_metric(self.macro_median_latency_seconds),
            _rank_metric(self.macro_median_input_tokens),
        )


@dataclass(frozen=True)
class ExperimentSummary:
    eligible: tuple[ExposureMode, ...]
    winners: tuple[ExposureMode, ...]
    selected: ExposureMode | None
    is_tie: bool
    scores: dict[ExposureMode, VariantScore]


def rank_variants(
    records: list[RunRecord] | tuple[RunRecord, ...], checks: ExperimentChecks
) -> ExperimentSummary:
    cases = tuple(sorted({record.case_id for record in records}))
    scores = {mode: _score(mode, records, cases) for mode in ExposureMode}
    eligible = tuple(
        mode for mode in ExposureMode if _is_eligible(mode, records, cases, checks.for_mode(mode))
    )
    if not eligible:
        return ExperimentSummary(
            eligible=(), winners=(), selected=None, is_tie=False, scores=scores
        )

    best_key = min(scores[mode].ranking_key for mode in eligible)
    winners = tuple(mode for mode in eligible if scores[mode].ranking_key == best_key)
    return ExperimentSummary(
        eligible=eligible,
        winners=winners,
        selected=winners[0],
        is_tie=len(winners) > 1,
        scores=scores,
    )


def _is_eligible(
    mode: ExposureMode,
    records: list[RunRecord] | tuple[RunRecord, ...],
    cases: tuple[str, ...],
    checks: VariantChecks | None,
) -> bool:
    if checks is None or not checks.safety_passed or not checks.heldout_schema_passed:
        return False
    return bool(cases) and all(
        sum(
            record.mode is mode
            and record.case_id == case
            and isinstance(record.outcome, RunSucceeded)
            for record in records
        )
        >= 2
        for case in cases
    )


def _score(
    mode: ExposureMode,
    records: list[RunRecord] | tuple[RunRecord, ...],
    cases: tuple[str, ...],
) -> VariantScore:
    successful = [
        record
        for record in records
        if record.mode is mode and isinstance(record.outcome, RunSucceeded)
    ]
    return VariantScore(
        correct_repetitions=len(successful),
        macro_median_model_requests=_macro_median(
            successful, cases, lambda metrics: float(metrics.model_request_count)
        ),
        macro_median_latency_seconds=_macro_median(
            successful, cases, lambda metrics: metrics.latency_seconds
        ),
        macro_median_input_tokens=_macro_median(
            successful, cases, lambda metrics: float(metrics.input_tokens)
        ),
    )


def _macro_median(
    records: list[RunRecord],
    cases: tuple[str, ...],
    value: Callable[[CompleteMetrics], float],
) -> float | None:
    values_by_case: list[float] = []
    for case in cases:
        values: list[float] = []
        for record in records:
            if record.case_id == case and isinstance(record.outcome, RunSucceeded):
                metric_value = value(record.outcome.metrics)
                values.append(metric_value)
        if values:
            values_by_case.append(float(median(values)))
    return float(median(values_by_case)) if values_by_case else None


def _rank_metric(value: float | None) -> float:
    return value if value is not None else float("inf")


def records_to_json(records: list[RunRecord] | tuple[RunRecord, ...]) -> bytes:
    return TypeAdapter(list[RunRecord]).dump_json(list(records), indent=2)


def records_from_json(raw: bytes | str) -> list[RunRecord]:
    return TypeAdapter(list[RunRecord]).validate_json(raw)
