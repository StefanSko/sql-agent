from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from functools import partial
from pathlib import Path
from uuid import uuid4

from ag_ui.core import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastmcp import FastMCP
from pydantic import ValidationError
from pydantic_ai import AgentRunResult
from pydantic_ai.messages import ModelMessage, TextPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.ui.ag_ui import AGUIAdapter
from pydantic_ai.usage import RunUsage

from sql_agent.agent import (
    FINAL_ANSWER_TOOL_NAME,
    RequestDeps,
    build_database_agent,
    ollama_model,
)
from sql_agent.mcp.server import create_database_server
from sql_agent.settings import Settings
from sql_agent.types import AgentAnswer

_FRONTEND_DIST = Path(__file__).parents[3] / "frontend" / "dist"


def create_app(
    *,
    settings: Settings | None = None,
    database: FastMCP | None = None,
    model: Model | None = None,
    usage_sink: Callable[[RunUsage], None] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_database = database or create_database_server(
        resolved_settings.dsn,
        row_cap=resolved_settings.row_cap,
        statement_timeout_ms=resolved_settings.statement_timeout_ms,
    )
    agent = build_database_agent(model or ollama_model(resolved_settings), resolved_database)
    app = FastAPI(title="Schema-generic SQL agent")

    frontend_index = _FRONTEND_DIST / "index.html"
    if (_FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> Response:
        if not frontend_index.is_file():
            return HTMLResponse(
                "Frontend not built. Run npm --prefix frontend ci &amp;&amp; "
                "npm --prefix frontend run build, then restart the server.",
                status_code=503,
            )
        return FileResponse(frontend_index, headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/agui")
    async def agui(request: Request) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        try:
            adapter = await AGUIAdapter[RequestDeps, AgentAnswer].from_request(request, agent=agent)
        except ValidationError as error:
            try:
                content = error.json()
            except ValueError:
                content = error.json(include_input=False)
            return Response(content=content, media_type="application/json", status_code=422)
        events = adapter.run_stream(
            deps=RequestDeps(request_id=request_id),
            model_settings=OpenAIChatModelSettings(
                max_tokens=resolved_settings.max_output_tokens,
                openai_reasoning_effort=(None if resolved_settings.agui_model_thinking else "none"),
            ),
            on_complete=partial(_answer_events, usage_sink=usage_sink),
        )
        return adapter.streaming_response(_validated_answer_stream(events))

    return app


async def _validated_answer_stream(events: AsyncIterator[BaseEvent]) -> AsyncIterator[BaseEvent]:
    pending_text: list[BaseEvent] = []
    hidden_tool_ids: set[str] = set()
    async for event in events:
        match event:
            case TextMessageStartEvent():
                pending_text = [event]
            case TextMessageContentEvent() | TextMessageEndEvent():
                if pending_text:
                    pending_text.append(event)
            case ToolCallStartEvent(tool_call_id=tool_call_id) if (
                event.tool_call_name == FINAL_ANSWER_TOOL_NAME
            ):
                hidden_tool_ids.add(tool_call_id)
            case (
                ToolCallArgsEvent(tool_call_id=tool_call_id)
                | ToolCallEndEvent(tool_call_id=tool_call_id)
            ) if tool_call_id in hidden_tool_ids:
                pass
            case ToolCallResultEvent(tool_call_id=tool_call_id) if tool_call_id in hidden_tool_ids:
                hidden_tool_ids.remove(tool_call_id)
            case RunFinishedEvent():
                for text_event in pending_text:
                    yield text_event
                yield event
            case RunErrorEvent():
                pending_text.clear()
                yield event
            case _:
                yield event


async def _answer_events(
    result: AgentRunResult[AgentAnswer],
    *,
    usage_sink: Callable[[RunUsage], None] | None,
) -> AsyncIterator[TextMessageStartEvent | TextMessageContentEvent | TextMessageEndEvent]:
    if usage_sink is not None:
        usage_sink(result.usage)
    if not should_bridge_answer(tuple(result.new_messages()), result.output.answer):
        return
    message_id = str(uuid4())
    yield TextMessageStartEvent(message_id=message_id)
    yield TextMessageContentEvent(message_id=message_id, delta=result.output.answer)
    yield TextMessageEndEvent(message_id=message_id)


def should_bridge_answer(messages: tuple[ModelMessage, ...], answer: str) -> bool:
    normalized_answer = " ".join(answer.split())
    streamed_text = "".join(
        part.content for message in messages for part in message.parts if isinstance(part, TextPart)
    )
    return " ".join(streamed_text.split()) != normalized_answer
