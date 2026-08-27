from __future__ import annotations

from pathlib import Path


def test_compose_keeps_ollama_private_and_gates_agent_on_exact_model() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    ollama_block = compose.split("  ollama:", 1)[1].split("  ollama-init:", 1)[0]
    assert "ports:" not in ollama_block
    assert "gemma4:12b-it-q4_K_M" in compose
    assert "service_completed_successfully" in compose
    assert "ollama show" in compose
    assert "db-mcp:" not in compose


def test_postgres_is_profiled_and_agent_has_healthcheck() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'profiles: ["postgres"]' in compose
    assert compose.count("healthcheck:") >= 3
    assert "agent-api" in compose
    assert "/health" in compose
    assert "agent_reader" in compose
    assert "CREATE ROLE agent_reader" in Path("docker/postgres-init.sql").read_text(
        encoding="utf-8"
    )
