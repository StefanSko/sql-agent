from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastmcp import Client
from pydantic import TypeAdapter
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings

from sql_agent.agent import AgentRun, RequestDeps, build_agent, ollama_model, run_agent
from sql_agent.mcp.client import parse_tool_result
from sql_agent.mcp.server import create_db_mcp
from sql_agent.metrics import (
    CompleteMetrics,
    ExperimentChecks,
    ExperimentSummary,
    FailureKind,
    RunFailed,
    RunRecord,
    RunSucceeded,
    VariantChecks,
    rank_variants,
)
from sql_agent.pglite import PGliteConfig, start_pglite
from sql_agent.seed import reset_database
from sql_agent.settings import Dsn, Settings
from sql_agent.types import ExposureMode, QueryOk, QueryRejected, QueryResult
from sql_agent.workload import WORKLOAD_VERSION, WorkloadCase, load_workload

_ROOT = Path(__file__).parents[3]


@dataclass(frozen=True)
class ModelMetadata:
    name: str
    digest: str
    modified_at: str
    family: str
    parameter_size: str
    quantization_level: str
    context_length: int


@dataclass(frozen=True)
class ExperimentMetadata:
    executed_at: str
    workload_version: str
    model: ModelMetadata
    repetitions: int
    warmup_runs: int
    seed: int
    timeout_seconds: float
    temperature: float
    pydantic_ai_version: str
    fastmcp_version: str
    mode_orders: tuple[tuple[ExposureMode, ...], ...]


@dataclass(frozen=True)
class ExperimentArtifact:
    metadata: ExperimentMetadata
    checks: ExperimentChecks
    records: tuple[RunRecord, ...]
    summary: ExperimentSummary


@dataclass(frozen=True)
class _TagDetails:
    family: str
    parameter_size: str
    quantization_level: str
    context_length: int


@dataclass(frozen=True)
class _Tag:
    name: str
    modified_at: str
    digest: str
    details: _TagDetails


@dataclass(frozen=True)
class _TagsResponse:
    models: tuple[_Tag, ...]


def rotation_order(repetition: int) -> tuple[ExposureMode, ...]:
    modes = tuple(ExposureMode)
    offset = repetition % len(modes)
    return modes[offset:] + modes[:offset]


async def run_experiment(
    settings: Settings,
    *,
    repetitions: int,
    seed: int,
    timeout_seconds: float,
) -> ExperimentArtifact:
    if repetitions < 3:
        raise ValueError("the exposure experiment requires at least three repetitions")
    workload = load_workload()
    model_metadata = await fetch_model_metadata(settings)
    await warm_model(settings)

    with TemporaryDirectory(prefix="sql-agent-experiment-") as temporary:
        directory = Path(temporary)
        pglite = await start_pglite(
            PGliteConfig(
                manager_path=_ROOT / "backend" / "pglite_manager.js",
                database_directory=directory / "db",
                ready_file=directory / "ready",
            )
        )
        try:
            safety = await _safety_results(pglite.dsn, workload[0])
            records = await _run_matrix(
                settings,
                pglite.dsn,
                workload,
                repetitions=repetitions,
                seed=seed,
                timeout_seconds=timeout_seconds,
            )
        finally:
            await pglite.stop()

    checks = ExperimentChecks(
        variants=tuple(
            VariantChecks(
                mode=mode,
                safety_passed=safety[mode],
                heldout_schema_passed=_heldout_passed(records, workload, mode),
            )
            for mode in ExposureMode
        )
    )
    summary = rank_variants(records, checks)
    metadata = ExperimentMetadata(
        executed_at=datetime.now(UTC).isoformat(),
        workload_version=WORKLOAD_VERSION,
        model=model_metadata,
        repetitions=repetitions,
        warmup_runs=1,
        seed=seed,
        timeout_seconds=timeout_seconds,
        temperature=0.0,
        pydantic_ai_version=version("pydantic-ai-slim"),
        fastmcp_version=version("fastmcp"),
        mode_orders=tuple(rotation_order(repetition) for repetition in range(repetitions)),
    )
    return ExperimentArtifact(
        metadata=metadata,
        checks=checks,
        records=records,
        summary=summary,
    )


async def _run_matrix(
    settings: Settings,
    dsn: Dsn,
    workload: tuple[WorkloadCase, ...],
    *,
    repetitions: int,
    seed: int,
    timeout_seconds: float,
) -> tuple[RunRecord, ...]:
    records: list[RunRecord] = []
    run_order = 0
    model = ollama_model(settings)
    for repetition in range(repetitions):
        run_seed = seed + repetition
        for case in workload:
            for mode in rotation_order(repetition):
                await reset_database(
                    dsn,
                    _ROOT / case.schema_path,
                    _ROOT / case.seed_directory if case.seed_directory is not None else None,
                )
                run_order += 1
                record = await _run_case(
                    model,
                    settings,
                    dsn,
                    case,
                    mode,
                    repetition=repetition,
                    run_order=run_order,
                    seed=run_seed,
                    timeout_seconds=timeout_seconds,
                )
                records.append(record)
    return tuple(records)


async def _run_case(
    model: Model,
    settings: Settings,
    dsn: Dsn,
    case: WorkloadCase,
    mode: ExposureMode,
    *,
    repetition: int,
    run_order: int,
    seed: int,
    timeout_seconds: float,
) -> RunRecord:
    db_mcp = create_db_mcp(
        dsn,
        row_cap=settings.row_cap,
        statement_timeout_ms=settings.statement_timeout_ms,
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            execution = await run_agent(
                build_agent(model),
                case.prompt,
                db_mcp,
                mode,
                RequestDeps(request_id=f"experiment-{run_order}"),
                stream_events=True,
                model_settings=OpenAIChatModelSettings(temperature=0.0, seed=seed),
            )
    except TimeoutError:
        outcome = RunFailed(kind=FailureKind.TIMEOUT, detail="run exceeded experiment timeout")
    except UnexpectedModelBehavior:
        outcome = RunFailed(
            kind=FailureKind.RETRY_EXHAUSTED,
            detail="model exhausted the configured validation/tool retries",
        )
    except Exception as error:
        outcome = RunFailed(
            kind=FailureKind.EXECUTION_ERROR,
            detail=f"run failed with {type(error).__name__}",
        )
    else:
        metrics = _complete_metrics(execution)
        outcome = (
            RunSucceeded(metrics=metrics)
            if case.oracle(execution.query_results, execution.answer)
            else RunFailed(
                kind=FailureKind.WRONG_RESULT,
                detail="typed query/output oracle did not match",
                metrics=metrics,
            )
        )
    return RunRecord(
        workload_version=WORKLOAD_VERSION,
        mode=mode,
        case_id=case.case_id,
        repetition=repetition,
        run_order=run_order,
        seed=seed,
        outcome=outcome,
    )


def _complete_metrics(execution: AgentRun) -> CompleteMetrics:
    return CompleteMetrics(
        latency_seconds=execution.latency_seconds,
        first_event_seconds=execution.first_event_seconds,
        model_request_count=execution.model_request_count,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        retries=execution.retries,
        mcp_calls=execution.mcp_calls,
    )


async def _safety_results(dsn: Dsn, case: WorkloadCase) -> dict[ExposureMode, bool]:
    results: dict[ExposureMode, bool] = {}
    for mode in ExposureMode:
        await reset_database(
            dsn,
            _ROOT / case.schema_path,
            _ROOT / case.seed_directory if case.seed_directory is not None else None,
        )
        db_mcp = create_db_mcp(dsn)
        async with Client(db_mcp.server) as client:
            write = parse_tool_result(
                await client.call_tool(
                    "run_query", {"sql": "DELETE FROM information_schema.tables"}
                ),
                TypeAdapter(QueryResult),
            )
            multiple = parse_tool_result(
                await client.call_tool("run_query", {"sql": "SELECT 1; SELECT 2"}),
                TypeAdapter(QueryResult),
            )
            read = parse_tool_result(
                await client.call_tool("run_query", {"sql": "SELECT 1 AS safety_value"}),
                TypeAdapter(QueryResult),
            )
        results[mode] = (
            isinstance(write, QueryRejected)
            and isinstance(multiple, QueryRejected)
            and isinstance(read, QueryOk)
            and read.rows[0].values == {"safety_value": 1}
        )
    return results


def _heldout_passed(
    records: tuple[RunRecord, ...],
    workload: tuple[WorkloadCase, ...],
    mode: ExposureMode,
) -> bool:
    heldout_ids = {case.case_id for case in workload if case.dataset.startswith("heldout")}
    return bool(heldout_ids) and all(
        sum(
            record.mode is mode
            and record.case_id == case_id
            and isinstance(record.outcome, RunSucceeded)
            for record in records
        )
        >= 2
        for case_id in heldout_ids
    )


async def fetch_model_metadata(settings: Settings) -> ModelMetadata:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{_ollama_root(settings)}/api/tags")
    response.raise_for_status()
    tags = TypeAdapter(_TagsResponse).validate_python(response.json())
    selected = next((tag for tag in tags.models if tag.name == settings.model_name), None)
    if selected is None:
        raise RuntimeError(f"configured model tag {settings.model_name!r} is not installed")
    return ModelMetadata(
        name=selected.name,
        digest=selected.digest,
        modified_at=selected.modified_at,
        family=selected.details.family,
        parameter_size=selected.details.parameter_size,
        quantization_level=selected.details.quantization_level,
        context_length=selected.details.context_length,
    )


async def warm_model(settings: Settings) -> None:
    headers = {"authorization": f"Bearer {settings.ollama_api_key.get_secret_value()}"}
    payload = {
        "model": settings.model_name,
        "messages": [{"role": "user", "content": "Reply with ready."}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{str(settings.ollama_base_url).rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
    response.raise_for_status()


def _ollama_root(settings: Settings) -> str:
    base = str(settings.ollama_base_url).rstrip("/")
    return base.removesuffix("/v1")


def save_artifact(artifact: ExperimentArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TypeAdapter(ExperimentArtifact).dump_json(artifact, indent=2))


def load_artifact(path: Path) -> ExperimentArtifact:
    return TypeAdapter(ExperimentArtifact).validate_json(path.read_bytes())


def summary_markdown(artifact: ExperimentArtifact) -> str:
    lines = [
        "# Exposure experiment summary",
        "",
        f"- Executed: {artifact.metadata.executed_at}",
        f"- Model: `{artifact.metadata.model.name}` (`{artifact.metadata.model.digest}`)",
        f"- Workload: v{artifact.metadata.workload_version}",
        f"- Repetitions: {artifact.metadata.repetitions}",
        "",
        "| mode | eligible | correct | request macro-median | latency macro-median | "
        "input-token macro-median |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode in ExposureMode:
        score = artifact.summary.scores[mode]
        lines.append(
            f"| {mode.value} | {'yes' if mode in artifact.summary.eligible else 'no'} | "
            f"{score.correct_repetitions} | {_format_metric(score.macro_median_model_requests)} | "
            f"{_format_metric(score.macro_median_latency_seconds, suffix='s', digits=3)} | "
            f"{_format_metric(score.macro_median_input_tokens)} |"
        )
    winners = ", ".join(mode.value for mode in artifact.summary.winners) or "none"
    selected = artifact.summary.selected.value if artifact.summary.selected is not None else "none"
    lines.extend(
        [
            "",
            f"- Evidence winner(s): **{winners}**",
            f"- Provisional application mode: **{selected}**",
            f"- Exact tie: **{'yes' if artifact.summary.is_tie else 'no'}**",
            "",
            "Failed repetitions count against correctness and are excluded from metric medians.",
        ]
    )
    return "\n".join(lines) + "\n"


def _format_metric(value: float | None, *, suffix: str = "", digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and summarize the exposure experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output", type=Path, default=Path("experiments/records/latest.json"))
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("artifact", type=Path)
    summarize.add_argument("--output", type=Path, default=Path("experiments/summaries/latest.md"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "run":
        artifact = asyncio.run(
            run_experiment(
                Settings.from_env(),
                repetitions=args.repetitions,
                seed=args.seed,
                timeout_seconds=args.timeout,
            )
        )
        save_artifact(artifact, args.output)
        summary_path = Path("experiments/summaries/latest.md")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary_markdown(artifact), encoding="utf-8")
        print(f"wrote {args.output} and {summary_path}")
    elif args.command == "summarize":
        artifact = load_artifact(args.artifact)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(summary_markdown(artifact), encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
