from __future__ import annotations

from fastmcp.client.client import CallToolResult
from pydantic import TypeAdapter


def parse_tool_result[T](result: CallToolResult, adapter: TypeAdapter[T]) -> T:
    if result.is_error:
        raise RuntimeError(_error_text(result))
    content = result.structured_content
    if content is not None and set(content) == {"result"}:
        content = content["result"]
    return adapter.validate_python(content)


def _error_text(result: CallToolResult) -> str:
    return " ".join(getattr(content, "text", "MCP tool call failed") for content in result.content)
