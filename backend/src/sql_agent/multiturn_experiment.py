from __future__ import annotations

import argparse
import asyncio
import copy
import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import cast
from uuid import uuid4

import httpx
from ag_ui.core import RunAgentInput
from pydantic import TypeAdapter
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.ui.ag_ui import AGUIAdapter
from pydantic_ai.usage import RunUsage

from sql_agent.agent import RequestDeps, build_agent, ollama_model, run_agent
from sql_agent.app import create_app
from sql_agent.db_mcp import create_db_mcp
from sql_agent.experiment import ModelMetadata, fetch_model_metadata, warm_model
from sql_agent.history import HistoryPolicy, compact_tool_history
from sql_agent.multiturn import MultiTurnMeasurement, ResendAssessment, assess_full_resend
from sql_agent.pglite import PGliteConfig, start_pglite
from sql_agent.seed import reset_database
from sql_agent.settings import Dsn, Settings
from sql_agent.types import ExposureMode
from sql_agent.workload import load_workload

_ROOT = Path(__file__).parents[3]
_JOURNEY_PATH = _ROOT / "data" / "workloads" / "multiturn-v1.json"


@dataclass(frozen=True)
class JourneyTurn:
    prompt: str
    expected_text: str


class ContextRetention(StrEnum):
    PRESERVED = "preserved"
    LOST = "lost"
    UNPROVEN = "unproven"


@dataclass(frozen=True)
class HistoryCompactionEvidence:
    framework_hook: str
    custom_processor_source_lines: int
    keep_recent_tool_pairs: int
    original_messages: int
    compacted_messages: int
    original_payload_bytes: int
    compacted_payload_bytes: int
    full_input_tokens: int
    compacted_input_tokens: int
    token_reduction: int
    compacted_latency_seconds: float
    correct: bool
    context_retention: ContextRetention
    failure_detail: str | None


@dataclass(frozen=True)
class MultiTurnMetadata:
    executed_at: str
    journey_version: str
    model: ModelMetadata
    exposure_mode: ExposureMode


@dataclass(frozen=True)
class MultiTurnArtifact:
    metadata: MultiTurnMetadata
    measurements: tuple[MultiTurnMeasurement, ...]
    assessment: ResendAssessment
    compaction: HistoryCompactionEvidence


def apply_agui_events(
    messages: list[dict[str, object]], events: tuple[dict[str, object], ...]
) -> None:
    for event in events:
        event_type = event.get("type")
        if event_type == "TEXT_MESSAGE_START":
            messages.append({"id": str(event["messageId"]), "role": "assistant", "content": ""})
        elif event_type == "TEXT_MESSAGE_CONTENT":
            message = _message_by_id(messages, str(event["messageId"]))
            if message is not None:
                message["content"] = str(message.get("content", "")) + str(event["delta"])
        elif event_type == "TOOL_CALL_START":
            call_id = str(event["toolCallId"])
            parent_id = str(event.get("parentMessageId") or f"assistant-{call_id}")
            owner = _message_by_id(messages, parent_id)
            if owner is None:
                new_owner: dict[str, object] = {
                    "id": parent_id,
                    "role": "assistant",
                    "content": None,
                    "toolCalls": [],
                }
                messages.append(new_owner)
                owner = new_owner
            calls = owner.get("toolCalls")
            if not isinstance(calls, list):
                calls = []
                owner["toolCalls"] = calls
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(event["toolCallName"]),
                        "arguments": "",
                    },
                }
            )
        elif event_type == "TOOL_CALL_ARGS":
            call = _tool_call_by_id(messages, str(event["toolCallId"]))
            if call is not None:
                function = call.get("function")
                if isinstance(function, dict):
                    function["arguments"] = str(function.get("arguments", "")) + str(event["delta"])
        elif event_type == "TOOL_CALL_RESULT":
            messages.append(
                {
                    "id": str(event["messageId"]),
                    "role": "tool",
                    "content": str(event["content"]),
                    "toolCallId": str(event["toolCallId"]),
                }
            )
        elif event_type == "REASONING_ENCRYPTED_VALUE":
            entity_id = str(event["entityId"])
            if event.get("subtype") == "tool-call":
                call = _tool_call_by_id(messages, entity_id)
                if call is not None:
                    call["encryptedValue"] = str(event["encryptedValue"])
            elif event.get("subtype") == "message":
                message = _message_by_id(messages, entity_id)
                if message is not None:
                    message["encryptedValue"] = str(event["encryptedValue"])


def _message_by_id(messages: list[dict[str, object]], message_id: str) -> dict[str, object] | None:
    return next((message for message in messages if message.get("id") == message_id), None)


def _tool_call_by_id(messages: list[dict[str, object]], call_id: str) -> dict[str, object] | None:
    for message in messages:
        calls = message.get("toolCalls")
        if not isinstance(calls, list):
            continue
        for raw_call in calls:
            if isinstance(raw_call, dict) and raw_call.get("id") == call_id:
                return cast(dict[str, object], raw_call)
    return None


def _events(response_text: str) -> tuple[dict[str, object], ...]:
    return tuple(
        TypeAdapter(dict[str, object]).validate_json(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    )


def _input_tokens(events: tuple[dict[str, object], ...]) -> int:
    finished = next(
        (event for event in reversed(events) if event.get("type") == "RUN_FINISHED"), None
    )
    if finished is None:
        return 0
    usage = finished.get("usage")
    if not isinstance(usage, list):
        return 0
    return sum(int(item.get("inputTokens") or 0) for item in usage if isinstance(item, dict))


def _answer_text(events: tuple[dict[str, object], ...]) -> str:
    return "".join(
        str(event.get("delta", ""))
        for event in events
        if event.get("type") == "TEXT_MESSAGE_CONTENT"
    )


def _request_payload(messages: list[dict[str, object]], *, run_id: str) -> dict[str, object]:
    return {
        "threadId": "multiturn-v1",
        "runId": run_id,
        "state": {},
        "messages": messages,
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


async def run_multiturn_experiment(settings: Settings) -> MultiTurnArtifact:
    turns = tuple(TypeAdapter(list[JourneyTurn]).validate_json(_JOURNEY_PATH.read_bytes()))
    if len(turns) != 10:
        raise ValueError("the multi-turn journey must contain exactly ten turns")
    model_metadata = await fetch_model_metadata(settings)
    await warm_model(settings)
    case = load_workload()[0]

    with TemporaryDirectory(prefix="sql-agent-multiturn-") as temporary:
        directory = Path(temporary)
        pglite = await start_pglite(
            PGliteConfig(
                manager_path=_ROOT / "backend" / "pglite_manager.js",
                database_directory=directory / "db",
                ready_file=directory / "ready",
            )
        )
        try:
            await reset_database(
                pglite.dsn,
                _ROOT / case.schema_path,
                _ROOT / case.seed_directory if case.seed_directory is not None else None,
            )
            db_mcp = create_db_mcp(pglite.dsn)
            app_settings = settings.model_copy(
                update={"dsn": pglite.dsn, "exposure_mode": ExposureMode.PREFETCHED}
            )
            model = ollama_model(settings)
            captured_usage: list[RunUsage] = []
            app = create_app(
                settings=app_settings,
                db_mcp=db_mcp,
                model=model,
                usage_sink=captured_usage.append,
            )
            history: list[dict[str, object]] = []
            measurements: list[MultiTurnMeasurement] = []
            history_before_tenth: list[dict[str, object]] = []
            tenth_prompt = turns[-1].prompt

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://probe"
            ) as client:
                for turn_number, turn in enumerate(turns, start=1):
                    if turn_number == 10:
                        history_before_tenth = copy.deepcopy(history)
                    history.append({"id": str(uuid4()), "role": "user", "content": turn.prompt})
                    payload = _request_payload(history, run_id=str(uuid4()))
                    request_bytes = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
                    usage_count = len(captured_usage)
                    started = monotonic()
                    response = await client.post("/agui", json=payload)
                    latency = monotonic() - started
                    response.raise_for_status()
                    response_events = _events(response.text)
                    answer = _answer_text(response_events)
                    correct = turn.expected_text in answer and not any(
                        event.get("type") == "RUN_ERROR" for event in response_events
                    )
                    measurements.append(
                        MultiTurnMeasurement(
                            turn=turn_number,
                            request_bytes=request_bytes,
                            input_tokens=(
                                captured_usage[-1].input_tokens
                                if len(captured_usage) > usage_count
                                else 0
                            ),
                            latency_seconds=latency,
                            correct=correct,
                            context_limit=model_metadata.context_length,
                        )
                    )
                    apply_agui_events(history, response_events)

            compaction = await _compaction_evidence(
                settings,
                pglite.dsn,
                history_before_tenth,
                tenth_prompt,
                turns[-1].expected_text,
                measurements[-1],
            )
        finally:
            await pglite.stop()

    checkpoints = tuple(
        measurement for measurement in measurements if measurement.turn in {1, 5, 10}
    )
    return MultiTurnArtifact(
        metadata=MultiTurnMetadata(
            executed_at=datetime.now(UTC).isoformat(),
            journey_version="1",
            model=model_metadata,
            exposure_mode=ExposureMode.PREFETCHED,
        ),
        measurements=tuple(measurements),
        assessment=assess_full_resend(checkpoints),
        compaction=compaction,
    )


async def _compaction_evidence(
    settings: Settings,
    dsn: Dsn,
    wire_history: list[dict[str, object]],
    prompt: str,
    expected_text: str,
    full_tenth: MultiTurnMeasurement,
) -> HistoryCompactionEvidence:
    model = ollama_model(settings)
    agent_without_processor = build_agent(model)
    run_input = RunAgentInput.model_validate(_request_payload(wire_history, run_id=str(uuid4())))
    model_history = tuple(AGUIAdapter(agent_without_processor, run_input).messages)
    policy = HistoryPolicy(keep_recent_tool_pairs=2)
    compacted_history = compact_tool_history(list(model_history), policy)
    original_bytes = len(ModelMessagesTypeAdapter.dump_json(list(model_history)))
    compacted_bytes = len(ModelMessagesTypeAdapter.dump_json(compacted_history))
    usage = RunUsage()
    started = monotonic()
    try:
        execution = await run_agent(
            build_agent(model, history_policy=policy),
            f"{prompt} Return the required structured final result.",
            create_db_mcp(dsn),
            ExposureMode.PREFETCHED,
            RequestDeps(request_id="multiturn-compacted"),
            message_history=model_history,
            stream_events=True,
            model_settings=OpenAIChatModelSettings(
                temperature=0.0,
                seed=42,
                openai_reasoning_effort=(None if settings.agui_model_thinking else "none"),
            ),
            usage=usage,
        )
    except UnexpectedModelBehavior as error:
        compacted_input_tokens = usage.input_tokens
        compacted_latency = monotonic() - started
        correct = False
        context_retention = ContextRetention.UNPROVEN
        failure_detail = f"compacted run failed with {type(error).__name__}"
    else:
        compacted_input_tokens = execution.input_tokens
        compacted_latency = execution.latency_seconds
        correct = expected_text in execution.answer.answer
        context_retention = ContextRetention.PRESERVED if correct else ContextRetention.LOST
        failure_detail = None
    source_lines = len(inspect.getsourcelines(compact_tool_history)[0])
    return HistoryCompactionEvidence(
        framework_hook="pydantic_ai.capabilities.ProcessHistory",
        custom_processor_source_lines=source_lines,
        keep_recent_tool_pairs=policy.keep_recent_tool_pairs,
        original_messages=len(model_history),
        compacted_messages=len(compacted_history),
        original_payload_bytes=original_bytes,
        compacted_payload_bytes=compacted_bytes,
        full_input_tokens=full_tenth.input_tokens,
        compacted_input_tokens=compacted_input_tokens,
        token_reduction=full_tenth.input_tokens - compacted_input_tokens,
        compacted_latency_seconds=compacted_latency,
        correct=correct,
        context_retention=context_retention,
        failure_detail=failure_detail,
    )


def save_multiturn_artifact(artifact: MultiTurnArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TypeAdapter(MultiTurnArtifact).dump_json(artifact, indent=2))


def load_multiturn_artifact(path: Path) -> MultiTurnArtifact:
    return TypeAdapter(MultiTurnArtifact).validate_json(path.read_bytes())


def multiturn_summary(artifact: MultiTurnArtifact) -> str:
    lines = [
        "# Full-history resend experiment",
        "",
        f"- Model: `{artifact.metadata.model.name}`",
        f"- Context limit: {artifact.metadata.model.context_length}",
        f"- Assessment: **{artifact.assessment.value}**",
        "",
        "| turn | request bytes | input tokens | latency | correct |",
        "|---:|---:|---:|---:|---:|",
    ]
    for measurement in artifact.measurements:
        if measurement.turn in {1, 5, 10}:
            lines.append(
                f"| {measurement.turn} | {measurement.request_bytes} | "
                f"{measurement.input_tokens} | {measurement.latency_seconds:.3f}s | "
                f"{'yes' if measurement.correct else 'no'} |"
            )
    compaction = artifact.compaction
    lines.extend(
        [
            "",
            "## ProcessHistory comparison",
            "",
            f"- Custom processor: {compaction.custom_processor_source_lines} source lines; "
            f"framework wiring: `{compaction.framework_hook}`.",
            f"- Serialized model history: {compaction.original_payload_bytes} → "
            f"{compaction.compacted_payload_bytes} bytes.",
            f"- Turn-10 input tokens: {compaction.full_input_tokens} → "
            f"{compaction.compacted_input_tokens} "
            f"({_token_delta_text(compaction.token_reduction)}).",
            f"- Compacted run correct: {'yes' if compaction.correct else 'no'}; "
            f"context retention: {compaction.context_retention.value}.",
            f"- Compacted failure: {compaction.failure_detail or 'none'}.",
        ]
    )
    return "\n".join(lines) + "\n"


def _token_delta_text(reduction: int) -> str:
    return f"{reduction} fewer" if reduction >= 0 else f"{-reduction} more"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the versioned full-history resend probe")
    parser.add_argument("--output", type=Path, default=Path("experiments/multiturn/latest.json"))
    args = parser.parse_args()
    artifact = asyncio.run(run_multiturn_experiment(Settings.from_env()))
    save_multiturn_artifact(artifact, args.output)
    summary_path = Path("experiments/multiturn/summary.md")
    summary_path.write_text(multiturn_summary(artifact), encoding="utf-8")
    print(f"wrote {args.output} and {summary_path}")


if __name__ == "__main__":
    main()
