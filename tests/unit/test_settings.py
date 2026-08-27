from __future__ import annotations

import pytest
from pydantic import ValidationError

from sql_agent.settings import Dsn, ExposureName, Settings


def test_settings_parse_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQL_AGENT_DSN", "postgresql://sentinel:secret@db/probe")
    monkeypatch.setenv("SQL_AGENT_OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("SQL_AGENT_MODEL_NAME", "configured-model")
    monkeypatch.setenv("SQL_AGENT_OLLAMA_API_KEY", "configured-key")
    monkeypatch.setenv("SQL_AGENT_EXPOSURE_MODE", "catalog")

    settings = Settings.from_env()

    assert settings.dsn == Dsn("postgresql://sentinel:secret@db/probe")
    assert settings.model_name == "configured-model"
    assert settings.exposure_mode is ExposureName.CATALOG
    assert settings.ollama_api_key.get_secret_value() == "configured-key"


def test_settings_have_no_url_model_or_dsn_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SQL_AGENT_DSN",
        "SQL_AGENT_OLLAMA_BASE_URL",
        "SQL_AGENT_MODEL_NAME",
        "SQL_AGENT_OLLAMA_API_KEY",
        "SQL_AGENT_EXPOSURE_MODE",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        Settings.from_env()
