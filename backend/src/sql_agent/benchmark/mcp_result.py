from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastmcp.client.client import CallToolResult
from pydantic import TypeAdapter


def parse_tool_result[T](result: CallToolResult, adapter: TypeAdapter[T]) -> T:
    if result.is_error:
        raise RuntimeError(_error_text(result))
    data = result.data
    if is_dataclass(data) and not isinstance(data, type):
        data = asdict(data)
    return adapter.validate_python(data)


def _error_text(result: CallToolResult) -> str:
    return " ".join(getattr(content, "text", "MCP tool call failed") for content in result.content)
