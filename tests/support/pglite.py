from __future__ import annotations

import csv
import socket
import subprocess
import time
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from sql_agent.settings import Dsn

ROOT = Path(__file__).parents[2]


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="session")
def pglite_dsn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Dsn]:
    directory = tmp_path_factory.mktemp("pglite")
    ready_file = directory / "ready"
    port = _unused_port()
    process = subprocess.Popen(
        [
            "node",
            str(ROOT / "backend" / "pglite_manager.js"),
            "--db",
            str(directory / "db"),
            "--port",
            str(port),
            "--ready-file",
            str(ready_file),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 30
    while not ready_file.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if not ready_file.exists():
        output = process.stdout.read() if process.stdout is not None else ""
        process.terminate()
        raise RuntimeError(f"PGlite did not start: {output}")

    try:
        yield Dsn(f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres?sslmode=disable")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def load_dataset(dsn: Dsn, schema_path: Path, csv_directory: Path | None) -> None:
    connection = await asyncpg.connect(str(dsn), ssl=False)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await connection.execute(schema_path.read_text(encoding="utf-8"))
        if csv_directory is None:
            return
        for path in sorted(csv_directory.glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                columns = tuple(reader.fieldnames or ())
            if rows:
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
                    tuple(_csv_value(row[column], data_types[column]) for column in columns)
                    for row in rows
                ]
                await connection.executemany(
                    f'INSERT INTO "{path.stem}" ({", ".join(columns)}) VALUES ({placeholders})',
                    values,
                )
    finally:
        connection.terminate()


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


@pytest_asyncio.fixture
async def seeded_dsn(pglite_dsn: Dsn) -> Dsn:
    await load_dataset(pglite_dsn, ROOT / "data" / "schema.sql", ROOT / "data" / "seed")
    return pglite_dsn
