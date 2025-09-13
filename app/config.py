"""Application configuration using pydantic-settings.

Environment variables (prefix LOCALAPI_):
- LOCALAPI_API_HOST (default: 0.0.0.0)
- LOCALAPI_API_PORT (default: 8080)
- LOCALAPI_DATABASE_PATH (default: data/local_api.db)
- LOCALAPI_LLM_BASE_URL (default: http://192.168.0.111:1234/v1)
- LOCALAPI_LLM_MODEL (default: local-model)
- LOCALAPI_VISION_MODEL (default: qwen2.5-vl-7b-instruct@q8_0)
- LOCALAPI_TEMPERATURE (default: 0.2)
- LOCALAPI_MAX_TOKENS (default: 512)
- LOCALAPI_MAX_CONTEXT_MESSAGES (default: 20)
- LOCALAPI_SUMMARIZE_AFTER_MESSAGES (default: 100)
- LOCALAPI_REQUEST_TIMEOUT (seconds, default: 120)
- LOCALAPI_LOG_LEVEL (default: INFO)
- LOCALAPI_FILES_DIR (default: files)
"""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    database_path: str = Field(default="data/local_api.db")

    llm_base_url: str = Field(default="http://192.168.0.111:1234/v1")
    llm_model: str = Field(default="local-model")
    vision_model: str = Field(default="qwen2.5-vl-7b-instruct@q8_0")

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1)

    max_context_messages: int = Field(default=20, ge=1)
    summarize_after_messages: int = Field(default=100, ge=2)

    request_timeout: float = Field(default=120.0, ge=1.0)

    log_level: str = Field(default="INFO")
    files_dir: str = Field(default="files")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LOCALAPI_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
