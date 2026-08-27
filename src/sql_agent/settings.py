from __future__ import annotations

from typing import NewType

from pydantic import HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from sql_agent.types import ExposureMode

Dsn = NewType("Dsn", str)
ExposureName = ExposureMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SQL_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    dsn: Dsn
    ollama_base_url: HttpUrl
    model_name: str
    ollama_api_key: SecretStr
    exposure_mode: ExposureMode
    row_cap: PositiveInt = 200
    statement_timeout_ms: PositiveInt = 5_000
    agui_model_thinking: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        return cls()
