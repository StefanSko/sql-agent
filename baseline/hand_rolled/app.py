from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from baseline.hand_rolled.agent import run_loop
from baseline.hand_rolled.mcp_backend import FastMcpBackend
from baseline.hand_rolled.openai_model import OpenAICompatibleModel
from sql_agent.mcp.server import create_db_mcp
from sql_agent.settings import Settings

_INDEX = Path(__file__).with_name("index.html")


def create_app() -> FastAPI:
    settings = Settings.from_env()
    backend = FastMcpBackend(
        create_db_mcp(
            settings.dsn,
            row_cap=settings.row_cap,
            statement_timeout_ms=settings.statement_timeout_ms,
        ).server
    )
    model = OpenAICompatibleModel(
        base_url=str(settings.ollama_base_url),
        api_key=settings.ollama_api_key.get_secret_value(),
        model_name=settings.model_name,
    )
    app = FastAPI(title="Hand-rolled SQL-agent control")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX.read_text(encoding="utf-8")

    @app.post("/sse")
    async def sse(request: Request) -> StreamingResponse:
        body = await request.json()
        prompt = str(body.get("prompt", ""))

        async def stream() -> AsyncIterator[str]:
            async for event in run_loop(prompt, model, backend):
                yield f"data: {json.dumps(asdict(event))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
