from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import asyncpg
import sqlparse
from fastmcp import FastMCP
from sqlparse import tokens
from sqlparse.sql import Function, TokenList

from sql_agent.settings import Dsn
from sql_agent.types import (
    Catalog,
    ColumnSchema,
    QueryOk,
    QueryRejected,
    QueryResult,
    QueryRow,
    QueryTruncated,
    TableNames,
    TableSchema,
)

_READ_ONLY_REASON: Final = "query rejected by read-only transaction"
_PROHIBITED_REASON: Final = "query uses a prohibited database capability"
_PROHIBITED_FUNCTIONS: Final = frozenset(
    {
        "dblink_connect",
        "dblink_exec",
        "lo_export",
        "lo_import",
        "pg_ls_dir",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_stat_file",
    }
)
_ALLOWED_FIRST_KEYWORDS: Final = frozenset({"EXPLAIN", "SELECT", "SHOW", "TABLE", "VALUES", "WITH"})
_WRITE_FIRST_KEYWORDS: Final = frozenset(
    {"ALTER", "CREATE", "DELETE", "DROP", "INSERT", "MERGE", "TRUNCATE", "UPDATE"}
)


@dataclass(frozen=True)
class DatabaseConfig:
    dsn: Dsn
    row_cap: int
    statement_timeout_ms: int


@dataclass(frozen=True)
class DbCall:
    tool_name: str
    query_result: QueryResult | None = None


class _Database:
    _config: DatabaseConfig

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config

    async def list_tables(self) -> TableNames:
        connection = await self._connect()
        try:
            records = await connection.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            return TableNames(names=tuple(record["table_name"] for record in records))
        finally:
            _close_connection(connection)

    async def describe_table(self, name: str) -> TableSchema:
        connection = await self._connect()
        try:
            records = await connection.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                name,
            )
        finally:
            _close_connection(connection)
        if not records:
            raise ValueError(f"unknown table {name!r}")
        return TableSchema(
            name=name,
            columns=tuple(
                ColumnSchema(
                    name=record["column_name"],
                    data_type=record["data_type"],
                    nullable=record["is_nullable"] == "YES",
                )
                for record in records
            ),
        )

    async def get_catalog(self) -> Catalog:
        names = await self.list_tables()
        return Catalog(tables=tuple([await self.describe_table(name) for name in names.names]))

    async def run_query(self, sql: str) -> QueryResult:
        statements = tuple(statement for statement in sqlparse.split(sql) if statement.strip())
        if len(statements) != 1:
            return QueryRejected(reason="exactly one SQL statement is required")
        parsed = sqlparse.parse(statements[0])[0]
        first_keyword = _first_keyword(parsed)
        if _contains_write_keyword(parsed):
            return QueryRejected(reason=_READ_ONLY_REASON)
        if first_keyword not in _ALLOWED_FIRST_KEYWORDS:
            return QueryRejected(reason=_PROHIBITED_REASON)
        if _function_names(parsed) & _PROHIBITED_FUNCTIONS:
            return QueryRejected(reason=_PROHIBITED_REASON)

        connection: asyncpg.Connection | None = None
        try:
            connection = await self._connect()
            async with connection.transaction(readonly=True):
                await connection.execute(
                    f"SET LOCAL statement_timeout = {self._config.statement_timeout_ms:d}"
                )
                records: list[asyncpg.Record] = []
                cursor = connection.cursor(
                    statements[0],
                    prefetch=1,
                    timeout=self._config.statement_timeout_ms / 1_000,
                )
                async for record in cursor:
                    records.append(record)
                    if len(records) > self._config.row_cap:
                        break
        except asyncpg.ReadOnlySQLTransactionError:
            return QueryRejected(reason=_READ_ONLY_REASON)
        except (asyncpg.QueryCanceledError, TimeoutError):
            return QueryRejected(reason="query exceeded the statement timeout")
        except asyncpg.PostgresError as error:
            sqlstate = getattr(error, "sqlstate", None)
            suffix = f" ({sqlstate})" if isinstance(sqlstate, str) else ""
            return QueryRejected(reason=f"database rejected the query{suffix}")
        except (OSError, ValueError):
            return QueryRejected(reason="database unavailable")
        finally:
            if connection is not None:
                _close_connection(connection)

        rows = tuple(
            QueryRow.from_mapping(dict(record)) for record in records[: self._config.row_cap]
        )
        if len(records) > self._config.row_cap:
            return QueryTruncated(rows=rows, row_cap=self._config.row_cap)
        return QueryOk(rows=rows)

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(str(self._config.dsn), ssl=False)


class DbMcp:
    server: FastMCP
    _calls: list[DbCall]
    _record_calls: bool

    def __init__(self, database: _Database) -> None:
        self.server = FastMCP("schema-generic-read-only-database", mask_error_details=True)
        self._calls = []
        self._record_calls = True

        @self.server.tool(description="List the names of queryable tables in the database schema.")
        async def list_tables() -> TableNames:
            result = await database.list_tables()
            self._record(DbCall(tool_name="list_tables"))
            return result

        @self.server.tool(
            description="Describe the columns, data types, and nullability of one queryable table."
        )
        async def describe_table(name: str) -> TableSchema:
            result = await database.describe_table(name)
            self._record(DbCall(tool_name="describe_table"))
            return result

        @self.server.tool(description="Return typed schema descriptions for all queryable tables.")
        async def get_catalog() -> Catalog:
            result = await database.get_catalog()
            self._record(DbCall(tool_name="get_catalog"))
            return result

        @self.server.tool(
            description=(
                "Execute exactly one read-only SQL statement. The result reports rows, "
                "truncation, or a safe rejection explicitly."
            )
        )
        async def run_query(sql: str) -> QueryResult:
            result = await database.run_query(sql)
            self._record(DbCall(tool_name="run_query", query_result=result))
            return result

    @property
    def calls(self) -> tuple[DbCall, ...]:
        return tuple(self._calls)

    def call_count(self) -> int:
        return len(self._calls)

    def disable_call_recording(self) -> None:
        self._calls.clear()
        self._record_calls = False

    def _record(self, call: DbCall) -> None:
        if self._record_calls:
            self._calls.append(call)


def _first_keyword(statement: TokenList) -> str | None:
    first = statement.token_first(skip_cm=True)
    return first.normalized if first is not None else None


def _contains_write_keyword(statement: TokenList) -> bool:
    return any(
        token.ttype in (tokens.Keyword.DML, tokens.Keyword.DDL)
        and token.normalized in _WRITE_FIRST_KEYWORDS
        for token in statement.flatten()
    )


def _function_names(token: TokenList) -> frozenset[str]:
    names: set[str] = set()
    for child in token.tokens:
        if isinstance(child, Function):
            name = child.get_name()
            if name is not None:
                names.add(name.lower())
        if isinstance(child, TokenList):
            names.update(_function_names(child))
    return frozenset(names)


def _close_connection(connection: asyncpg.Connection) -> None:
    connection.terminate()


def create_db_mcp(
    dsn: Dsn,
    *,
    row_cap: int = 200,
    statement_timeout_ms: int = 5_000,
) -> DbMcp:
    config = DatabaseConfig(
        dsn=dsn,
        row_cap=row_cap,
        statement_timeout_ms=statement_timeout_ms,
    )
    return DbMcp(_Database(config))
