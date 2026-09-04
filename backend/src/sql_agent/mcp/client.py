from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastmcp import Client, FastMCP
from pydantic import TypeAdapter

from sql_agent.types import Catalog

_CATALOG = TypeAdapter(Catalog)


async def fetch_catalog(server: FastMCP) -> Catalog:
    """Fetch and normalize the catalog over modern MCP v2."""
    async with Client(server, mode="auto") as client:
        result = await client.call_tool("get_catalog", {}, raise_on_error=False)
    if result.is_error:
        raise RuntimeError("database catalog unavailable")
    data = result.data
    if is_dataclass(data) and not isinstance(data, type):
        data = asdict(data)
    return _CATALOG.validate_python(data)
