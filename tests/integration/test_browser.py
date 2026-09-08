from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from ag_ui.core import AssistantMessage, RunAgentInput, ToolMessage
from fastapi import FastAPI
from playwright.sync_api import Page, Request, expect, sync_playwright
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sql_agent.app import create_app
from sql_agent.settings import Dsn
from tests.integration.test_agui_app import settings
from tests.support.models import (
    FailingStreamModel,
    catalog_model,
    retrying_catalog_model,
    streaming_function_model,
)
from tests.support.pglite import ROOT


@contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Browser test server did not start"
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Browser test server did not stop"


@pytest.fixture(scope="session")
def frontend_build() -> None:
    subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True)


@pytest.fixture
def page(seeded_dsn: Dsn, frontend_build: None) -> Iterator[Page]:
    # Seed before Playwright's sync API starts its own event loop.
    del seeded_dsn, frontend_build
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            yield page
            assert not errors, errors
        finally:
            browser.close()


def ask(page: Page, question: str) -> None:
    page.get_by_role("textbox", name="Question").fill(question)
    page.get_by_role("button", name="Send", exact=True).click()


def test_browser_round_trips_tool_history_through_real_agui(page: Page, seeded_dsn: Dsn) -> None:
    seen: list[list[ModelMessage]] = []
    payloads: list[RunAgentInput] = []

    def capture(request: Request) -> None:
        if request.url.endswith("/agui") and request.method == "POST":
            payloads.append(RunAgentInput.model_validate(request.post_data_json))

    page.on("request", capture)
    app = create_app(settings=settings(seeded_dsn), model=catalog_model(seen))
    with serve(app) as url:
        page.goto(url)
        expect(page.get_by_role("heading", name="SQL Agent")).to_be_visible()
        expect(page.get_by_role("button", name="Send", exact=True)).to_be_disabled()
        ask(page, "What tables exist?")
        expect(page.get_by_text("The database has three tables.", exact=True)).to_be_visible()
        tool = page.locator("summary", has_text="run_query")
        expect(tool).to_contain_text("Complete")
        tool.click()
        expect(page.get_by_text("SELECT COUNT(*)", exact=False)).to_be_visible()
        page.get_by_role("textbox", name="Question").fill("Check again using the earlier result.")
        page.get_by_role("textbox", name="Question").press("Enter")
        expect(page.get_by_text("The database has three tables.", exact=True)).to_have_count(2)
        assert len(payloads) == 2
        history = payloads[1].messages
        calls = [
            call
            for message in history
            if isinstance(message, AssistantMessage)
            for call in message.tool_calls or []
        ]
        results = [message for message in history if isinstance(message, ToolMessage)]
        assert calls and calls[0].function.name == "run_query"
        assert results and results[0].tool_call_id == calls[0].id
        assert "table_count" in results[0].content
        assert payloads[0].thread_id == payloads[1].thread_id
        assert payloads[0].run_id != payloads[1].run_id
        assert payloads[1].tools == []
        assert "Check again using the earlier result." in repr(seen)
        assert "submit_answer" not in page.locator("body").inner_text()
        page.reload()
        expect(page.get_by_text("The database has three tables.", exact=True)).to_have_count(0)
        ask(page, "A fresh conversation")
        expect(page.get_by_text("The database has three tables.", exact=True)).to_be_visible()
        assert payloads[2].thread_id != payloads[0].thread_id
        assert len(payloads[2].messages) == 1


def test_browser_only_displays_validated_answer(page: Page, seeded_dsn: Dsn) -> None:
    app = create_app(settings=settings(seeded_dsn), model=retrying_catalog_model())
    with serve(app) as url:
        page.goto(url)
        ask(page, "How many trips?")
        expect(page.get_by_text("There are 8 trips.", exact=True)).to_be_visible()
        expect(page.locator("body")).not_to_contain_text("LEAKED")
        expect(page.locator("body")).not_to_contain_text("submit_answer")


def test_browser_displays_run_error_and_can_send_again(page: Page, seeded_dsn: Dsn) -> None:
    app = create_app(settings=settings(seeded_dsn), model=FailingStreamModel().as_model())
    with serve(app) as url:
        page.goto(url)
        ask(page, "Fail this run")
        expect(page.get_by_role("alert")).to_contain_text("Request failed")
        expect(page.locator("body")).not_to_contain_text("partial")
        page.get_by_role("textbox", name="Question").fill("Try again")
        expect(page.get_by_role("button", name="Send", exact=True)).to_be_enabled()


def test_browser_displays_http_error_and_recovers(page: Page, seeded_dsn: Dsn) -> None:
    app = create_app(settings=settings(seeded_dsn), model=catalog_model())
    with serve(app) as url:
        page.goto(url)
        page.route("**/agui", lambda route: route.fulfill(status=503, body="Unavailable"))
        ask(page, "First attempt")
        expect(page.get_by_role("alert")).to_contain_text("Request failed")
        page.unroute("**/agui")
        ask(page, "Try again")
        expect(page.get_by_text("The database has three tables.", exact=True)).to_be_visible()
        expect(page.get_by_role("alert")).to_have_count(0)


def test_browser_can_stop_a_running_request(page: Page, seeded_dsn: Dsn) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        del messages, info
        try:
            started.set()
            yield "Unvalidated pending answer"
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    app = create_app(settings=settings(seeded_dsn), model=FunctionModel(stream_function=stream))
    with serve(app) as url:
        page.goto(url)
        ask(page, "A slow question")
        assert started.wait(timeout=5), "Model stream did not start"
        expect(page.get_by_role("status")).to_have_text("Working…")
        expect(page.locator("body")).not_to_contain_text("Unvalidated pending answer")
        page.get_by_role("button", name="Stop", exact=True).click()
        expect(page.get_by_role("status")).to_have_count(0)
        assert cancelled.wait(timeout=5), "Stop did not cancel the backend stream"
        page.get_by_role("textbox", name="Question").fill("Another question")
        expect(page.get_by_role("button", name="Send", exact=True)).to_be_enabled()
        expect(page.get_by_role("alert")).to_have_count(0)


def test_browser_renders_safe_markdown_on_mobile(page: Page, seeded_dsn: Dsn) -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answer": (
                            "**Verified** result.\n\n"
                            "<script>window.injected = true</script>\n\n"
                            "[Unsafe](javascript:alert(1))"
                        ),
                        "evidence": [],
                    },
                )
            ]
        )

    app = create_app(settings=settings(seeded_dsn), model=streaming_function_model(respond))
    with serve(app) as url:
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(url)
        ask(page, "Show a formatted answer")
        expect(page.locator("strong", has_text="Verified")).to_be_visible()
        assert page.evaluate("window.injected") is None
        assert page.locator('a[href^="javascript:"]').count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.get_by_role("textbox", name="Question")).to_be_in_viewport()


def test_vite_dev_proxy_reaches_real_agui(page: Page, seeded_dsn: Dsn, tmp_path: Path) -> None:
    app = create_app(settings=settings(seeded_dsn), model=catalog_model())
    with serve(app) as api_url, (tmp_path / "vite.log").open("w+") as log:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=ROOT / "frontend",
            env=os.environ | {"SQL_AGENT_DEV_API_URL": api_url},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        dev_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    ready = httpx.get(dev_url, timeout=1).status_code == 200
                    if ready:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            log.seek(0)
            assert ready, log.read()
            page.goto(dev_url)
            ask(page, "What tables exist?")
            expect(page.get_by_text("The database has three tables.", exact=True)).to_be_visible()
            expect(page.locator("summary", has_text="run_query")).to_contain_text("Complete")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
