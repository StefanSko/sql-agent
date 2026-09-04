from __future__ import annotations

import asyncio
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sql_agent.settings import Dsn


@dataclass(frozen=True)
class PGliteConfig:
    manager_path: Path
    database_directory: Path
    ready_file: Path
    startup_timeout_seconds: float = 30.0


class RunningPGlite:
    dsn: Dsn
    _process: subprocess.Popen[str]

    def __init__(self, dsn: Dsn, process: subprocess.Popen[str]) -> None:
        self.dsn = dsn
        self._process = process

    async def stop(self) -> None:
        self._process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(self._process.wait), timeout=3)
        except TimeoutError:
            self._process.kill()
            await asyncio.to_thread(self._process.wait)


async def start_pglite(config: PGliteConfig) -> RunningPGlite:
    port = _unused_port()
    process = subprocess.Popen(
        [
            "node",
            str(config.manager_path),
            "--db",
            str(config.database_directory),
            "--port",
            str(port),
            "--ready-file",
            str(config.ready_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = asyncio.get_running_loop().time() + config.startup_timeout_seconds
    while (
        not config.ready_file.exists()
        and process.poll() is None
        and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.05)
    if not config.ready_file.exists():
        output = process.stdout.read() if process.stdout is not None else ""
        process.kill()
        await asyncio.to_thread(process.wait)
        raise RuntimeError(f"PGlite failed to start: {output}")
    return RunningPGlite(
        Dsn(f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres?sslmode=disable"),
        process,
    )


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
