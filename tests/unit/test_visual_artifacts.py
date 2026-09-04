from __future__ import annotations

import re
from pathlib import Path

import pytest

ARTIFACTS = {
    "architecture.html": ("Why this shape", "In-process MCP"),
    "call-stack.html": ("Type journey", "QueryResult"),
    "benchmarks.html": ("Prefetched wins", "18 / 18"),
    "protocols.html": ("Handshake to sessionless", "2026-07-28", "Code Mode"),
    "verdict.html": ("Keep the typed core", "Product-fit filter"),
    "validation/index.html": ("Five ways to challenge the verdict", "Choose your evidence"),
    "validation/01-ablation-ladder.html": ("Ablation ladder", "Decision rule"),
    "validation/02-seam-swap.html": ("Seam-swap laboratory", "Decision rule"),
    "validation/03-client-gauntlet.html": ("Client gauntlet", "Decision rule"),
    "validation/04-chaos-tournament.html": ("Chaos tournament", "Decision rule"),
    "validation/05-shadow-economics.html": ("Shadow economics", "Decision rule"),
}


@pytest.mark.parametrize(("name", "required"), ARTIFACTS.items())
def test_visual_artifact_is_standalone_and_links_to_real_code(
    name: str, required: tuple[str, ...]
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
