from __future__ import annotations

from typing import cast

import pytest
from fastmcp import Client
from pydantic import TypeAdapter

from sql_agent.db_mcp import DbMcp, create_db_mcp
from sql_agent.mcp_client import parse_tool_result
from sql_agent.settings import Dsn
from sql_agent.types import Catalog, QueryOk, QueryRejected, QueryTruncated, TableNames, TableSchema


@pytest.fixture
def db_mcp(seeded_dsn: Dsn) -> DbMcp:
    return create_db_mcp(seeded_dsn, row_cap=2, statement_timeout_ms=2_000)


@pytest.mark.asyncio
async def test_list_tables_crosses_in_process_mcp_and_pglite(db_mcp: DbMcp) -> None:
    async with Client(db_mcp.server) as client:
        raw = await client.call_tool("list_tables", {})

    result = parse_tool_result(raw, TypeAdapter(TableNames))
    assert result.names == ("riders", "stations", "trips")


@pytest.mark.asyncio
async def test_describe_and_catalog_are_typed(db_mcp: DbMcp) -> None:
    async with Client(db_mcp.server) as client:
        described = parse_tool_result(
            await client.call_tool("describe_table", {"name": "trips"}),
            TypeAdapter(TableSchema),
        )
        catalog = parse_tool_result(await client.call_tool("get_catalog", {}), TypeAdapter(Catalog))

    assert described.name == "trips"
    assert described.columns[0].name == "trip_id"
    assert {table.name for table in catalog.tables} == {"riders", "stations", "trips"}


@pytest.mark.asyncio
async def test_run_query_returns_rows_and_explicit_truncation(db_mcp: DbMcp) -> None:
    async with Client(db_mcp.server) as client:
        aggregate = parse_tool_result(
            await client.call_tool(
                "run_query",
                {
                    "sql": "SELECT COUNT(*) AS member_trips FROM trips "
                    "JOIN riders USING (rider_id) WHERE riders.plan = 'member'"
                },
            ),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )
        capped = parse_tool_result(
            await client.call_tool(
                "run_query", {"sql": "SELECT trip_id FROM trips ORDER BY trip_id"}
            ),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )

    aggregate_ok = cast(QueryOk, aggregate)
    assert aggregate_ok.rows[0].values == {"member_trips": 6}
    assert isinstance(capped, QueryTruncated)
    assert [row.values for row in capped.rows] == [{"trip_id": 1}, {"trip_id": 2}]
    assert capped.row_cap == 2


@pytest.mark.asyncio
async def test_row_cap_stops_reading_before_slow_remaining_rows(seeded_dsn: Dsn) -> None:
    capped_mcp = create_db_mcp(seeded_dsn, row_cap=2, statement_timeout_ms=100)
    async with Client(capped_mcp.server) as client:
        result = parse_tool_result(
            await client.call_tool(
                "run_query",
                {"sql": "SELECT value, pg_sleep(0.02) FROM generate_series(1, 100) AS value"},
            ),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )

    assert isinstance(result, QueryTruncated)
    assert [row.values["value"] for row in result.rows] == [1, 2]


@pytest.mark.asyncio
async def test_run_query_rejects_multiple_statements_even_with_semicolon_in_string(
    db_mcp: DbMcp,
) -> None:
    async with Client(db_mcp.server) as client:
        accepted = parse_tool_result(
            await client.call_tool("run_query", {"sql": "SELECT ';' AS value;"}),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )
        rejected = parse_tool_result(
            await client.call_tool("run_query", {"sql": "SELECT 1; SELECT 2"}),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )

    assert isinstance(accepted, QueryOk)
    assert rejected == QueryRejected(reason="exactly one SQL statement is required")


@pytest.mark.asyncio
async def test_run_query_rejects_privileged_server_capabilities(db_mcp: DbMcp) -> None:
    async with Client(db_mcp.server) as client:
        file_read = parse_tool_result(
            await client.call_tool(
                "run_query", {"sql": "SELECT pg_read_file('/etc/passwd') AS contents"}
            ),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )
        program = parse_tool_result(
            await client.call_tool(
                "run_query", {"sql": "COPY (SELECT 1) TO PROGRAM 'echo unsafe'"}
            ),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )

    expected = QueryRejected(reason="query uses a prohibited database capability")
    assert file_read == expected
    assert program == expected


@pytest.mark.asyncio
async def test_nested_write_shapes_are_rejected_before_database_connection() -> None:
    unreachable = create_db_mcp(Dsn("postgresql://sentinel:secret@127.0.0.1:1/probe"))
    statements = (
        "WITH removed AS (DELETE FROM records RETURNING id) SELECT * FROM removed",
        "EXPLAIN ANALYZE DELETE FROM records",
    )

    async with Client(unreachable.server) as client:
        results = tuple(
            [
                parse_tool_result(
                    await client.call_tool("run_query", {"sql": statement}),
                    TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
                )
                for statement in statements
            ]
        )

    assert results == (
        QueryRejected(reason="query rejected by read-only transaction"),
        QueryRejected(reason="query rejected by read-only transaction"),
    )


@pytest.mark.asyncio
async def test_run_query_is_read_only(db_mcp: DbMcp) -> None:
    async with Client(db_mcp.server) as client:
        result = parse_tool_result(
            await client.call_tool("run_query", {"sql": "DELETE FROM trips"}),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )
        count = parse_tool_result(
            await client.call_tool("run_query", {"sql": "SELECT COUNT(*) AS count FROM trips"}),
            TypeAdapter(QueryOk | QueryTruncated | QueryRejected),
        )

    assert isinstance(result, QueryRejected)
    assert "read-only" in result.reason.lower()
    count_ok = cast(QueryOk, count)
    assert count_ok.rows[0].values == {"count": 8}


@pytest.mark.asyncio
async def test_dsn_is_absent_from_mcp_surface(db_mcp: DbMcp, seeded_dsn: Dsn) -> None:
    async with Client(db_mcp.server) as client:
        tools = await client.list_tools()
        result = await client.call_tool("list_tables", {})

    visible = f"{tools!r}\n{result!r}"
    assert str(seeded_dsn) not in visible
    assert "postgresql://" not in visible
