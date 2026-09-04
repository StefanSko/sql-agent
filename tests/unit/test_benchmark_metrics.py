from __future__ import annotations

from sql_agent.benchmark.metrics import (
    BenchmarkChecks,
    CompleteMetrics,
    FailureKind,
    RunFailed,
    RunRecord,
    RunSucceeded,
    VariantChecks,
    rank_variants,
    records_from_json,
    records_to_json,
)
from sql_agent.benchmark.types import ExposureMode


def success(
    mode: ExposureMode,
    case: str,
    repetition: int,
    *,
    requests: int,
    latency: float,
    tokens: int,
) -> RunRecord:
    return RunRecord(
        workload_version="1",
        mode=mode,
        case_id=case,
        repetition=repetition,
        run_order=repetition,
        seed=42,
        outcome=RunSucceeded(
            metrics=CompleteMetrics(
                latency_seconds=latency,
                first_event_seconds=latency / 2,
                model_request_count=requests,
                input_tokens=tokens,
                output_tokens=10,
                retries=0,
                mcp_calls=("run_query",),
            )
        ),
    )


def failure(mode: ExposureMode, case: str, repetition: int, kind: FailureKind) -> RunRecord:
    return RunRecord(
        workload_version="1",
        mode=mode,
        case_id=case,
        repetition=repetition,
        run_order=repetition,
        seed=None,
        outcome=RunFailed(kind=kind, detail="recorded failure"),
    )


def all_checks(*, prefetched_heldout: bool = True) -> BenchmarkChecks:
    return BenchmarkChecks(
        variants=tuple(
            VariantChecks(
                mode=mode,
                safety_passed=True,
                heldout_schema_passed=(
                    prefetched_heldout if mode is ExposureMode.PREFETCHED else True
                ),
            )
            for mode in ExposureMode
        )
    )


def complete_records() -> list[RunRecord]:
    records: list[RunRecord] = []
    for mode in ExposureMode:
        for case in ("one", "two"):
            records.extend(
                success(mode, case, repetition, requests=2, latency=2.0, tokens=200)
                for repetition in range(3)
            )
    return records


def test_timeout_wrong_and_incomplete_repetitions_count_as_failures() -> None:
    records = complete_records()
    records[-1:] = [failure(ExposureMode.PREFETCHED, "two", 2, FailureKind.TIMEOUT)]
    records[-2:-1] = [failure(ExposureMode.PREFETCHED, "two", 1, FailureKind.INCOMPLETE_METRICS)]

    summary = rank_variants(records, all_checks())

    assert ExposureMode.PREFETCHED not in summary.eligible
    assert summary.scores[ExposureMode.PREFETCHED].correct_repetitions == 4


def test_safety_and_heldout_checks_gate_eligibility() -> None:
    summary = rank_variants(complete_records(), all_checks(prefetched_heldout=False))

    assert summary.eligible == (ExposureMode.GRANULAR, ExposureMode.CATALOG)


def test_highest_total_correct_repetitions_wins_first() -> None:
    records = complete_records()
    records[-1] = failure(ExposureMode.PREFETCHED, "two", 2, FailureKind.WRONG_RESULT)
    records = [
        record if record.mode is not ExposureMode.PREFETCHED else _with_fast_metrics(record)
        for record in records
    ]

    summary = rank_variants(records, all_checks())

    assert summary.winners == (ExposureMode.GRANULAR, ExposureMode.CATALOG)


def _with_fast_metrics(record: RunRecord) -> RunRecord:
    if not isinstance(record.outcome, RunSucceeded):
        return record
    return success(
        record.mode,
        record.case_id,
        record.repetition,
        requests=1,
        latency=0.1,
        tokens=1,
    )


def test_ranking_compares_request_latency_then_tokens_in_correct_direction() -> None:
    request_records = complete_records()
    request_records = [
        _replace_metrics(record, requests={ExposureMode.GRANULAR: 3}.get(record.mode, 2))
        for record in request_records
    ]
    assert rank_variants(request_records, all_checks()).winners == (
        ExposureMode.CATALOG,
        ExposureMode.PREFETCHED,
    )

    latency_records = [
        _replace_metrics(
            record,
            requests=2,
            latency={ExposureMode.CATALOG: 1.0, ExposureMode.PREFETCHED: 1.5}.get(record.mode, 2.0),
        )
        for record in complete_records()
    ]
    assert rank_variants(latency_records, all_checks()).winners == (ExposureMode.CATALOG,)

    token_records = [
        _replace_metrics(
            record,
            requests=2,
            latency=1.0,
            tokens={ExposureMode.PREFETCHED: 100}.get(record.mode, 200),
        )
        for record in complete_records()
    ]
    assert rank_variants(token_records, all_checks()).winners == (ExposureMode.PREFETCHED,)


def _replace_metrics(
    record: RunRecord,
    *,
    requests: int,
    latency: float | None = None,
    tokens: int | None = None,
) -> RunRecord:
    if not isinstance(record.outcome, RunSucceeded):
        return record
    metrics = record.outcome.metrics
    return success(
        record.mode,
        record.case_id,
        record.repetition,
        requests=requests,
        latency=latency if latency is not None else metrics.latency_seconds,
        tokens=tokens if tokens is not None else metrics.input_tokens,
    )


def test_macro_median_weights_cases_equally() -> None:
    records = complete_records()
    records = [
        _replace_metrics(
            record,
            requests=1 if record.case_id == "one" else 5,
            latency=record.outcome.metrics.latency_seconds
            if isinstance(record.outcome, RunSucceeded)
            else None,
        )
        if record.mode is ExposureMode.GRANULAR
        else record
        for record in records
    ]

    score = rank_variants(records, all_checks()).scores[ExposureMode.GRANULAR]
    assert score.macro_median_model_requests == 3.0


def test_exact_tie_is_reported_and_declaration_order_selects_m4_default() -> None:
    summary = rank_variants(complete_records(), all_checks())

    assert summary.winners == tuple(ExposureMode)
    assert summary.selected is ExposureMode.GRANULAR
    assert summary.is_tie is True


def test_records_round_trip_as_typed_json() -> None:
    records = [
        *complete_records()[:1],
        failure(ExposureMode.CATALOG, "one", 3, FailureKind.RETRY_EXHAUSTED),
    ]

    assert records_from_json(records_to_json(records)) == records
