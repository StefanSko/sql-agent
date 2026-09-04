from __future__ import annotations

from dataclasses import dataclass, field

from baseline.hand_rolled.agent import (
    BaselineEvent,
    BaselineModel,
    BaselineText,
    BaselineToolCall,
    BaselineToolCalls,
    run_loop,
)
from baseline.hand_rolled.mcp_backend import FastMcpBackend
from sql_agent.mcp.server import create_db_mcp
from sql_agent.settings import Dsn


@dataclass
class ScriptedBaselineModel(BaselineModel):
    query: bool
    seen_results: list[str] = field(default_factory=list)

    async def complete(
        self, messages: tuple[dict[str, object], ...], tools: tuple[dict[str, object], ...]
    ) -> BaselineText | BaselineToolCalls:
        self.seen_results.extend(str(message) for message in messages if message["role"] == "tool")
        for message in messages:
            if message["role"] == "assistant" and message.get("tool_calls"):
                tool_calls = message["tool_calls"]
                assert isinstance(tool_calls, list)
                function = tool_calls[0]["function"]
                assert isinstance(function["arguments"], str)
        called = [message.get("name") for message in messages if message["role"] == "tool"]
        if "list_tables" not in called:
            return BaselineToolCalls(
                calls=(BaselineToolCall(call_id="1", name="list_tables", arguments={}),)
            )
        if self.query and "run_query" not in called:
            return BaselineToolCalls(
                calls=(
                    BaselineToolCall(
                        call_id="2",
                        name="run_query",
                        arguments={
                            "sql": "SELECT COUNT(*) AS member_trips FROM trips "
                            "JOIN riders USING (rider_id) WHERE riders.plan = 'member'"
                        },
                    ),
                )
            )
        return BaselineText(text="Member riders took 6 trips." if self.query else "Three tables.")


async def collect_events(model: ScriptedBaselineModel, dsn: Dsn) -> tuple[BaselineEvent, ...]:
    backend = FastMcpBackend(create_db_mcp(dsn).server)
    return tuple([event async for event in run_loop("question", model, backend)])


async def test_baseline_runs_m1_list_tables_journey(seeded_dsn: Dsn) -> None:
    events = await collect_events(ScriptedBaselineModel(query=False), seeded_dsn)

    assert [event.kind for event in events] == ["tool_call", "tool_result", "text", "done"]


async def test_baseline_runs_m2_safe_query_journey(seeded_dsn: Dsn) -> None:
    model = ScriptedBaselineModel(query=True)
    events = await collect_events(model, seeded_dsn)

    assert "member_trips" in "".join(model.seen_results)
    assert events[-2].content == "Member riders took 6 trips."
