from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from baseline.hand_rolled.agent import BaselineToolCallEvent, run_loop
from baseline.hand_rolled.mcp_backend import FastMcpBackend
from baseline.hand_rolled.openai_model import OpenAICompatibleModel
from sql_agent.agent import ollama_model
from sql_agent.app import create_app
from sql_agent.experiment import ModelMetadata, fetch_model_metadata, warm_model
from sql_agent.mcp.server import create_db_mcp
from sql_agent.multiturn_experiment import _answer_text, _events, _request_payload
from sql_agent.pglite import PGliteConfig, start_pglite
from sql_agent.seed import reset_database
from sql_agent.settings import Settings
from sql_agent.types import ExposureMode
from sql_agent.workload import load_workload

_ROOT = Path(__file__).parents[3]


@dataclass(frozen=True)
class ProtocolObservation:
    protocol: str
    event_types: tuple[str, ...]
    tool_names: tuple[str, ...]
    event_count: int
    latency_seconds: float
    final_text: str
    success: bool


@dataclass(frozen=True)
class SurfaceObservation:
    variant: str
    python_nonblank_lines: int
    browser_nonblank_lines: int


@dataclass(frozen=True)
class UIComparisonArtifact:
    executed_at: str
    model: ModelMetadata
    prompt: str
    agui: ProtocolObservation
    raw_sse: ProtocolObservation
    surfaces: tuple[SurfaceObservation, ...]


async def run_ui_comparison(settings: Settings) -> UIComparisonArtifact:
    metadata = await fetch_model_metadata(settings)
    await warm_model(settings)
    case = load_workload()[0]
    with TemporaryDirectory(prefix="sql-agent-ui-") as temporary:
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
            app_settings = settings.model_copy(
                update={"dsn": pglite.dsn, "exposure_mode": ExposureMode.PREFETCHED}
            )
            app = create_app(
                settings=app_settings,
                db_mcp=create_db_mcp(pglite.dsn),
                model=ollama_model(settings),
            )
            payload = _request_payload(
                [{"id": str(uuid4()), "role": "user", "content": case.prompt}],
                run_id=str(uuid4()),
            )
            started = monotonic()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://probe"
            ) as client:
                response = await client.post("/agui", json=payload)
            agui_latency = monotonic() - started
            response.raise_for_status()
            agui_events = _events(response.text)
            agui_text = _answer_text(agui_events)
            agui = ProtocolObservation(
                protocol="AG-UI",
                event_types=tuple(str(event["type"]) for event in agui_events),
                tool_names=tuple(
                    str(event["toolCallName"])
                    for event in agui_events
                    if event.get("type") == "TOOL_CALL_START"
                ),
                event_count=len(agui_events),
                latency_seconds=agui_latency,
                final_text=agui_text,
                success=(
                    str(case.expected.value) in agui_text
                    and not any(event.get("type") == "RUN_ERROR" for event in agui_events)
                ),
            )

            await reset_database(
                pglite.dsn,
                _ROOT / case.schema_path,
                _ROOT / case.seed_directory if case.seed_directory is not None else None,
            )
            baseline_model = OpenAICompatibleModel(
                base_url=str(settings.ollama_base_url),
                api_key=settings.ollama_api_key.get_secret_value(),
                model_name=settings.model_name,
            )
            started = monotonic()
            baseline_events = tuple(
                [
                    event
                    async for event in run_loop(
                        case.prompt,
                        baseline_model,
                        FastMcpBackend(create_db_mcp(pglite.dsn).server),
                    )
                ]
            )
            baseline_latency = monotonic() - started
            baseline_text = "".join(
                event.content for event in baseline_events if event.kind == "text"
            )
            raw_sse = ProtocolObservation(
                protocol="raw SSE",
                event_types=tuple(event.kind for event in baseline_events),
                tool_names=tuple(
                    event.content
                    for event in baseline_events
                    if isinstance(event, BaselineToolCallEvent)
                ),
                event_count=len(baseline_events),
                latency_seconds=baseline_latency,
                final_text=baseline_text,
                success=str(case.expected.value) in baseline_text,
            )
        finally:
            await pglite.stop()

    return UIComparisonArtifact(
        executed_at=datetime.now(UTC).isoformat(),
        model=metadata,
        prompt=case.prompt,
        agui=agui,
        raw_sse=raw_sse,
        surfaces=(
            SurfaceObservation(
                variant="Pydantic AI + AG-UI",
                python_nonblank_lines=_line_count(
                    (
                        _ROOT / "backend/src/sql_agent/agent.py",
                        _ROOT / "backend/src/sql_agent/app.py",
                    )
                ),
                browser_nonblank_lines=_line_count((_ROOT / "frontend/index.html",)),
            ),
            SurfaceObservation(
                variant="hand-rolled + raw SSE",
                python_nonblank_lines=_line_count(
                    (
                        _ROOT / "baseline/hand_rolled/agent.py",
                        _ROOT / "baseline/hand_rolled/app.py",
                    )
                ),
                browser_nonblank_lines=_line_count((_ROOT / "baseline/hand_rolled/index.html",)),
            ),
        ),
    )


def _line_count(paths: tuple[Path, ...]) -> int:
    return sum(
        bool(line.strip())
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def save_ui_comparison(artifact: UIComparisonArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TypeAdapter(UIComparisonArtifact).dump_json(artifact, indent=2))


def load_ui_comparison(path: Path) -> UIComparisonArtifact:
    return TypeAdapter(UIComparisonArtifact).validate_json(path.read_bytes())


def ui_summary(artifact: UIComparisonArtifact) -> str:
    agui_types = len(set(artifact.agui.event_types))
    raw_types = len(set(artifact.raw_sse.event_types))
    lines = [
        "# AG-UI versus raw-SSE journey",
        "",
        f"- Model: `{artifact.model.name}`",
        f"- AG-UI: {artifact.agui.event_count} events across {agui_types} event types; "
        f"success={'yes' if artifact.agui.success else 'no'}; "
        f"latency={artifact.agui.latency_seconds:.3f}s.",
        f"- Raw SSE: {artifact.raw_sse.event_count} events across {raw_types} event types; "
        f"success={'yes' if artifact.raw_sse.success else 'no'}; "
        f"latency={artifact.raw_sse.latency_seconds:.3f}s.",
        "",
        "| variant | Python nonblank lines | browser nonblank lines |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {surface.variant} | {surface.python_nonblank_lines} | "
        f"{surface.browser_nonblank_lines} |"
        for surface in artifact.surfaces
    )
    lines.extend(
        [
            "",
            "AG-UI supplies standard run, text, tool-call, tool-result, and usage lifecycle "
            "events. The raw control supplies only the five event kinds its UI currently needs.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the real AG-UI and raw-SSE journeys")
    parser.add_argument("--output", type=Path, default=Path("experiments/ui/latest.json"))
    args = parser.parse_args()
    artifact = asyncio.run(run_ui_comparison(Settings.from_env()))
    save_ui_comparison(artifact, args.output)
    summary = Path("experiments/ui/summary.md")
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(ui_summary(artifact), encoding="utf-8")
    print(f"wrote {args.output} and {summary}")


if __name__ == "__main__":
    main()
