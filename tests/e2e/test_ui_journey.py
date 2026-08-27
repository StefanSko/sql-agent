from __future__ import annotations

import os

import pytest

from sql_agent.settings import Settings
from sql_agent.ui_comparison import run_ui_comparison

pytestmark = pytest.mark.e2e


async def test_real_ui_journey_compares_agui_and_control() -> None:
    if os.environ.get("SQL_AGENT_RUN_LOCAL_E2E") != "1":
        pytest.skip("set SQL_AGENT_RUN_LOCAL_E2E=1 to run local Ollama tests")

    comparison = await run_ui_comparison(Settings.from_env())

    assert comparison.agui.success is True
    assert "TOOL_CALL_START" in comparison.agui.event_types
    assert "TOOL_CALL_RESULT" in comparison.agui.event_types
    assert comparison.raw_sse.success is True
    assert "tool_call" in comparison.raw_sse.event_types
    assert "tool_result" in comparison.raw_sse.event_types
