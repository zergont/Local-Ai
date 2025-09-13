"""Application settings using pydantic-settings.

Fields:
- LM_BASE_URL: Base URL for OpenAI-compatible API (default: http://192.168.0.111:1234/v1)
- MODEL_CONTROLLER: Default model/controller identifier (default: qwen/qwen3-30b-a3b)
- K: Number of last messages to include in context (default: 12)
- SUMMARY_TRIGGER: Message count threshold to trigger summarization (default: 16)
"""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LM_BASE_URL: str = Field(default="http://192.168.0.111:1234/v1")
    MODEL_CONTROLLER: str = Field(default="qwen/qwen3-30b-a3b")
    K: int = Field(default=12, ge=1)
    SUMMARY_TRIGGER: int = Field(default=16, ge=2)

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
