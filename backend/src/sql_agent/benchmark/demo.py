from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Literal

import asyncpg
import uvicorn
from fastmcp import Client
from pydantic import TypeAdapter
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings

from sql_agent.agent import RequestDeps, ollama_model
from sql_agent.app import create_app
from sql_agent.benchmark.demo_workload import (
    DATASET_DIRECTORY,
    DATASET_VERSION,
    Difficulty,
    EvaluationCase,
    GoldenCase,
    GoldenSuite,
    Split,
    file_sha256,
    load_cases,
    load_questions,
    rows_match,
)
from sql_agent.benchmark.execution import BenchmarkRun, run_agent
from sql_agent.benchmark.mcp_result import parse_tool_result
from sql_agent.benchmark.metrics import FailureKind
from sql_agent.benchmark.pglite import PGliteConfig, start_pglite
from sql_agent.benchmark.runner import ModelMetadata, fetch_model_metadata
from sql_agent.benchmark.seed import reset_database
from sql_agent.benchmark.types import ExposureMode
from sql_agent.mcp.server import create_database_server
from sql_agent.settings import Dsn, Settings
from sql_agent.types import QueryOk, QueryResult

_ROOT = Path(__file__).parents[4]


@dataclass(frozen=True)
class ResultCorrect:
    execution: BenchmarkRun
    kind: Literal["result_correct"] = field(default="result_correct", init=False)


@dataclass(frozen=True)
class ResultIncorrect:
    execution: BenchmarkRun
    kind: Literal["result_incorrect"] = field(default="result_incorrect", init=False)


@dataclass(frozen=True)
class EvaluationFailed:
    failure: FailureKind
    detail: str
    kind: Literal["run_failed"] = field(default="run_failed", init=False)


@dataclass(frozen=True)
class DemoRecord:
    case_id: str
    difficulty: Difficulty
    repetition: int
    seed: int
    elapsed_seconds: float
    outcome: ResultCorrect | ResultIncorrect | EvaluationFailed


@dataclass(frozen=True)
class DemoMetadata:
    executed_at: str
    dataset_version: str
    golden_sha256: str
    split: Split
    model: ModelMetadata
    repetitions: int
    timeout_seconds: float
    max_output_tokens: int
    row_cap: int
    statement_timeout_ms: int
    model_thinking: bool
    temperature: float
    pydantic_ai_version: str
    fastmcp_version: str


@dataclass(frozen=True)
class DemoReport:
    metadata: DemoMetadata
    records: tuple[DemoRecord, ...]


@asynccontextmanager
async def demo_database(directory: Path = DATASET_DIRECTORY) -> AsyncIterator[Dsn]:
    """Own a disposable database. Never reset the user's configured DSN."""
    with TemporaryDirectory(prefix="sql-agent-demo-") as temporary:
        root = Path(temporary)
        database = await start_pglite(
            PGliteConfig(
                manager_path=_ROOT / "backend" / "pglite_manager.js",
                database_directory=root / "db",
                ready_file=root / "ready",
            )
        )
        try:
            await reset_database(database.dsn, directory / "schema.sql", None)
            connection = await asyncpg.connect(str(database.dsn), ssl=False)
            try:
                async with connection.transaction():
                    await connection.execute((directory / "seed.sql").read_text())
            finally:
                connection.terminate()
            yield database.dsn
        finally:
            await database.stop()


async def verify_references(dsn: Dsn, cases: tuple[EvaluationCase, ...]) -> None:
    async with Client(create_database_server(dsn), mode="auto") as client:
        for case in cases:
            result = parse_tool_result(
                await client.call_tool("run_query", {"sql": case.reference_sql}),
                TypeAdapter(QueryResult),
            )
            if not rows_match(result, case.gold.result, case.question.ordering):
                raise ValueError(f"reference result mismatch: {case.question.case_id}: {result!r}")
    # PGlite shares session state across sockets. Do not leave oracle SQL discoverable
    # through pg_prepared_statements when handing this database to the model.
    connection = await asyncpg.connect(str(dsn), ssl=False, statement_cache_size=0)
    try:
        await connection.execute("DEALLOCATE ALL")
    finally:
        connection.terminate()


async def freeze_gold(dsn: Dsn, output: Path, directory: Path = DATASET_DIRECTORY) -> None:
    """Explicit maintainer operation; exclusive creation prevents accidental rebaselining."""
    if output.exists():
        raise FileExistsError(output)
    cases: list[GoldenCase] = []
    async with Client(create_database_server(dsn), mode="auto") as client:
        for question in load_questions(directory):
            path = directory / "reference" / f"{question.case_id}.sql"
            result = parse_tool_result(
                await client.call_tool("run_query", {"sql": path.read_text()}),
                TypeAdapter(QueryResult),
            )
            if not isinstance(result, QueryOk):
                raise ValueError(
                    f"reference did not produce complete rows: {question.case_id}: {result!r}"
                )
            cases.append(GoldenCase(question.case_id, file_sha256(path), result))
    gold = GoldenSuite(
        DATASET_VERSION,
        file_sha256(directory / "schema.sql"),
        file_sha256(directory / "seed.sql"),
        file_sha256(directory / "questions.json"),
        tuple(cases),
    )
    with output.open("xb") as stream:
        stream.write(TypeAdapter(GoldenSuite).dump_json(gold, indent=2) + b"\n")


async def run_case(
    model: Model,
    settings: Settings,
    case: EvaluationCase,
    *,
    repetition: int,
    seed: int,
    timeout_seconds: float,
) -> DemoRecord:
    started = monotonic()
    server = create_database_server(
        settings.dsn,
        row_cap=settings.row_cap,
        statement_timeout_ms=settings.statement_timeout_ms,
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            execution = await run_agent(
                model,
                case.question.prompt,
                server,
                ExposureMode.PREFETCHED,
                RequestDeps(request_id=f"demo-{case.question.case_id}-{repetition}"),
                model_settings=OpenAIChatModelSettings(
                    temperature=0.0,
                    seed=seed,
                    max_tokens=settings.max_output_tokens,
                    openai_reasoning_effort=None if settings.agui_model_thinking else "none",
                ),
            )
    except TimeoutError:
        outcome = EvaluationFailed(FailureKind.TIMEOUT, "run exceeded configured timeout")
    except UnexpectedModelBehavior:
        outcome = EvaluationFailed(
            FailureKind.RETRY_EXHAUSTED, "model exhausted validation retries"
        )
    except Exception as error:
        # Do not serialize exception text: provider errors can contain credentials/URLs.
        outcome = EvaluationFailed(FailureKind.EXECUTION_ERROR, type(error).__name__)
    else:
        # Only the final query counts, not a correct scalar buried in exploratory rows.
        correct = bool(execution.query_results) and rows_match(
            execution.query_results[-1],
            case.gold.result,
            case.question.ordering,
        )
        outcome = ResultCorrect(execution) if correct else ResultIncorrect(execution)
    return DemoRecord(
        case.question.case_id,
        case.question.difficulty,
        repetition,
        seed,
        monotonic() - started,
        outcome,
    )


def select_cases(split: Split, identifiers: list[str] | None) -> tuple[EvaluationCase, ...]:
    cases = load_cases(split)
    if identifiers is None:
        return cases
    unknown = set(identifiers) - {case.question.case_id for case in cases}
    if unknown:
        raise ValueError(f"cases not in {split.value} split: {', '.join(sorted(unknown))}")
    return tuple(case for case in cases if case.question.case_id in identifiers)


async def benchmark(
    settings: Settings,
    cases: tuple[EvaluationCase, ...],
    *,
    split: Split,
    repetitions: int,
    seed: int,
    timeout_seconds: float,
    output: Path,
) -> DemoReport:
    if repetitions < 1 or timeout_seconds <= 0 or not cases:
        raise ValueError("benchmark requires cases, positive repetitions and a positive timeout")
    metadata = DemoMetadata(
        executed_at=datetime.now(UTC).isoformat(),
        dataset_version=DATASET_VERSION,
        golden_sha256=file_sha256(DATASET_DIRECTORY / "golden.json"),
        split=split,
        model=await fetch_model_metadata(settings),
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        max_output_tokens=settings.max_output_tokens,
        row_cap=settings.row_cap,
        statement_timeout_ms=settings.statement_timeout_ms,
        model_thinking=settings.agui_model_thinking,
        temperature=0.0,
        pydantic_ai_version=version("pydantic-ai-slim"),
        fastmcp_version=version("fastmcp"),
    )
    await verify_references(settings.dsn, cases)
    records: list[DemoRecord] = []
    model = ollama_model(settings)
    for repetition in range(repetitions):
        for case in cases:
            record = await run_case(
                model,
                settings,
                case,
                repetition=repetition,
                seed=seed + repetition,
                timeout_seconds=timeout_seconds,
            )
            records.append(record)
            report = DemoReport(metadata, tuple(records))
            # Checkpoint each attempt, including failures, for interrupted long runs.
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_bytes(TypeAdapter(DemoReport).dump_json(report, indent=2) + b"\n")
            temporary.replace(output)
            print(
                f"{case.question.case_id} [{repetition + 1}]: {record.outcome.kind} "
                f"({record.elapsed_seconds:.2f}s)",
                flush=True,
            )
    return DemoReport(metadata, tuple(records))


def summary_markdown(report: DemoReport) -> str:
    rows = [
        "# Demo SQL execution benchmark",
        "",
        f"Dataset: {report.metadata.dataset_version}; split: {report.metadata.split.value}",
        f"Model: {report.metadata.model.name} ({report.metadata.model.digest})",
        "",
        "This scores complete final query results, not natural-language answer correctness.",
        "Column names, row order, duplicates and prescribed rounding are part of the contract.",
        "Timeouts/errors count as failures. Latency includes all attempts and cold starts.",
        "",
        "| Difficulty | Correct / attempted | Accuracy | Median latency |",
        "|---|---:|---:|---:|",
    ]
    for label, records in [
        *(
            (difficulty.value, tuple(r for r in report.records if r.difficulty is difficulty))
            for difficulty in Difficulty
        ),
        ("all", report.records),
    ]:
        if not records:
            continue
        correct = sum(isinstance(record.outcome, ResultCorrect) for record in records)
        rows.append(
            f"| {label} | {correct}/{len(records)} | {100 * correct / len(records):.1f}% | "
            f"{median(record.elapsed_seconds for record in records):.2f}s |"
        )
    return "\n".join(rows) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproducible large demo and held-out SQL benchmark"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="Check every frozen answer using MCP and disposable PGlite")
    questions = commands.add_parser(
        "questions", help="Print prompts only; no database/model required"
    )
    questions.add_argument("--split", type=Split, choices=list(Split), default=Split.DEVELOPMENT)
    serve = commands.add_parser(
        "serve", help="Serve the application against the large disposable demo"
    )
    serve.add_argument("--port", type=int, default=8000)
    freeze = commands.add_parser("freeze", help="Maintainers: create a NEW golden result file")
    freeze.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("benchmark", help="Score the production tool surface on one split")
    run.add_argument("--split", type=Split, choices=list(Split), default=Split.DEVELOPMENT)
    run.add_argument("--case", action="append", dest="identifiers")
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--output", type=Path)
    return parser


async def _main(args: argparse.Namespace) -> None:
    if args.command == "questions":
        for question in load_questions():
            if question.split is args.split:
                print(f"## {question.case_id} ({question.difficulty.value})\n\n{question.prompt}\n")
        return
    # Validate references and split selection before starting processes or contacting a model.
    if args.command == "benchmark":
        cases = select_cases(args.split, args.identifiers)
    elif args.command in {"verify", "serve"}:
        cases = load_cases(Split.DEVELOPMENT) + load_cases(Split.HELDOUT)
    else:
        cases = ()
    async with demo_database() as dsn:
        if args.command == "freeze":
            await freeze_gold(dsn, args.output)
            print(f"Created {args.output}; independently review before committing")
        elif args.command == "verify":
            await verify_references(dsn, cases)
            print(f"Verified {len(cases)} frozen reference results through MCP ({DATASET_VERSION})")
        elif args.command == "serve":
            await verify_references(dsn, cases)
            settings = Settings(dsn=dsn)
            print(
                f"Large demo ready at http://127.0.0.1:{args.port}; Ctrl+C cleans up the database",
                flush=True,
            )
            await uvicorn.Server(
                uvicorn.Config(
                    create_app(settings=settings),
                    host="127.0.0.1",
                    port=args.port,
                )
            ).serve()
        elif args.command == "benchmark":
            output = args.output or Path(f"benchmarks/records/demo-{args.split.value}.json")
            report = await benchmark(
                Settings(dsn=dsn),
                cases,
                split=args.split,
                repetitions=args.repetitions,
                seed=args.seed,
                timeout_seconds=args.timeout,
                output=output,
            )
            summary = summary_markdown(report)
            output.with_suffix(".md").write_text(summary)
            print(summary)


def main() -> None:
    asyncio.run(_main(_parser().parse_args()))


if __name__ == "__main__":
    main()
