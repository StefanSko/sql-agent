from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from functools import partial
from pathlib import Path
from typing import cast
from uuid import uuid4

from ag_ui.core import TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from pydantic_ai import AgentRunResult
from pydantic_ai.messages import ModelMessage, TextPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.ui.ag_ui import AGUIAdapter
from pydantic_ai.usage import RunUsage

from sql_agent.agent import RequestDeps, build_agent, ollama_model
from sql_agent.db_mcp import DbMcp, create_db_mcp
from sql_agent.exposure import prepare_exposure
from sql_agent.settings import Settings
from sql_agent.types import AgentAnswer

_FRONTEND_INDEX = Path(__file__).parents[3] / "frontend" / "index.html"


def create_app(
    *,
    settings: Settings | None = None,
    db_mcp: DbMcp | None = None,
    model: Model | None = None,
    usage_sink: Callable[[RunUsage], None] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_db = db_mcp or create_db_mcp(
        resolved_settings.dsn,
        row_cap=resolved_settings.row_cap,
        statement_timeout_ms=resolved_settings.statement_timeout_ms,
    )
    resolved_db.disable_call_recording()
    agent = build_agent(model or ollama_model(resolved_settings))
    app = FastAPI(title="Schema-generic SQL agent")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _FRONTEND_INDEX.read_text(encoding="utf-8")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/agui")
    async def agui(request: Request) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        setup = await prepare_exposure(resolved_db, resolved_settings.exposure_mode)
        return await AGUIAdapter.dispatch_request(
            request,
            agent=agent,
            deps=RequestDeps(request_id=request_id),
            instructions=setup.instructions,
            toolsets=[cast(AbstractToolset[RequestDeps], setup.toolset)],
            model_settings=OpenAIChatModelSettings(
                openai_reasoning_effort=(None if resolved_settings.agui_model_thinking else "none")
            ),
            on_complete=partial(_answer_events, usage_sink=usage_sink),
        )

    return app


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
