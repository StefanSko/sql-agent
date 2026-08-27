from __future__ import annotations

import re
from pathlib import Path

import pytest

ARTIFACTS = {
    "architecture.html": ("Why this shape", "In-process MCP"),
    "call-stack.html": ("Type journey", "QueryResult"),
    "benchmarks.html": ("Prefetched wins", "18 / 18"),
    "verdict.html": ("Keep the typed core", "Product-fit filter"),
}


@pytest.mark.parametrize(("name", "required"), ARTIFACTS.items())
def test_visual_artifact_is_standalone_and_links_to_real_code(
    name: str, required: tuple[str, str]
) -> None:
    artifact = Path("artifacts") / name
    html = artifact.read_text(encoding="utf-8")

    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "<script src=" not in html
    assert all(text in html for text in required)

    references = re.findall(r'data-code-ref="([^"#]+)#L(\d+)"', html)
    assert references
    for relative_path, raw_line in references:
        source = (artifact.parent / relative_path).resolve()
        assert source.is_file(), relative_path
        assert int(raw_line) <= len(source.read_text(encoding="utf-8").splitlines())
