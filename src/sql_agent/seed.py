from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import asyncpg

from sql_agent.settings import Dsn


async def reset_database(dsn: Dsn, schema_path: Path, seed_directory: Path | None) -> None:
    connection = await asyncpg.connect(str(dsn), ssl=False)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await connection.execute(schema_path.read_text(encoding="utf-8"))
        if seed_directory is None:
            return
        for path in sorted(seed_directory.glob("*.csv")):
            await _load_csv(connection, path)
    finally:
        connection.terminate()


async def _load_csv(connection: asyncpg.Connection, path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        columns = tuple(reader.fieldnames or ())
    if not rows:
        return
    type_rows = await connection.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        path.stem,
    )
    data_types = {row["column_name"]: row["data_type"] for row in type_rows}
    placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
    values = [
        tuple(_csv_value(row[column], data_types[column]) for column in columns) for row in rows
    ]
    await connection.executemany(
        f'INSERT INTO "{path.stem}" ({", ".join(columns)}) VALUES ({placeholders})',
        values,
    )


def _csv_value(raw: str, data_type: str) -> object:
    if not raw:
        return None
    if data_type in {"smallint", "integer", "bigint"}:
        return int(raw)
    if data_type in {"real", "double precision", "numeric", "decimal"}:
        return float(raw)
    if data_type == "date":
        return date.fromisoformat(raw)
    if data_type.startswith("timestamp"):
        return datetime.fromisoformat(raw)
    if data_type == "boolean":
        return raw.lower() in {"true", "t", "1"}
    return raw
