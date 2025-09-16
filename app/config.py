"""Application configuration using pydantic-settings.

Environment variables (prefix LOCALAPI_ by default). Also supports specific LOCALAI_* overrides
for upload settings to match UI requirements.

- LOCALAPI_API_HOST (default: 127.0.0.1)
- LOCALAPI_API_PORT (default: 8080)
- LOCALAPI_DATABASE_PATH (default: data/local_api.db)
- LOCALAPI_LLM_BASE_URL (default: http://192.168.0.111:1234/v1)
- LOCALAPI_LLM_MODEL (default: qwen/qwen3-14b)
- LOCALAPI_VISION_MODEL (default: qwen2.5-vl-7b-instruct@q8_0)
- LOCALAPI_TEMPERATURE (default: 0.2)
- LOCALAPI_MAX_TOKENS (default: 512)
- LOCALAPI_MAX_CONTEXT_MESSAGES (default: 20)
- LOCALAPI_SUMMARIZE_AFTER_MESSAGES (default: 100)
- LOCALAPI_REQUEST_TIMEOUT (seconds, default: 120)
- LOCALAPI_LOG_LEVEL (default: INFO)
- LOCALAPI_FILES_DIR (default: files)

Upload-related (also accepts LOCALAI_* overrides):
- LOCALAPI_MAX_UPLOAD_MB (default: 25)
- LOCALAPI_ALLOWED_EXTS (CSV, default: .png,.jpg,.jpeg,.webp,.gif,.pdf,.txt)
- LOCALAI_MAX_UPLOAD_MB (override)
- LOCALAI_ALLOWED_EXTS (override)

New context budget settings:
- LOCALAPI_CONTEXT_WINDOW_TOKENS (default: 32768)
- LOCALAPI_CONTEXT_PROMPT_BUDGET_RATIO (default: 0.6)
- LOCALAPI_CONTEXT_HYSTERESIS_TOKENS (default: 1024)
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8080)

    # Base public URL for generating absolute links (no trailing slash)
    app_base_url: str = Field(default="http://127.0.0.1:8080")

    database_path: str = Field(default="data/local_api.db")

    llm_base_url: str = Field(default="http://192.168.0.111:1234/v1")
    llm_model: str = Field(default="qwen/qwen3-14b")
    vision_model: str = Field(default="qwen2.5-vl-7b-instruct@q8_0")

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1)

    max_context_messages: int = Field(default=20, ge=1)
    summarize_after_messages: int = Field(default=100, ge=2)

    request_timeout: float = Field(default=120.0, ge=1.0)

    log_level: str = Field(default="INFO")
    files_dir: str = Field(default="files")

    # Upload settings (can be overridden by LOCALAI_* env vars)
    max_upload_mb: int = Field(default=25, ge=1)
    allowed_exts: List[str] = Field(default_factory=lambda: [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".pdf",
        ".txt",
    ])

    # ---- Context window budgeting ----
    # Maximum model context window (tokens)
    context_window_tokens: int = Field(default=32768, ge=1024)
    # Fraction of full window reserved for prompt (rest for completion)
    context_prompt_budget_ratio: float = Field(default=0.6, ge=0.1, le=0.9)
    # Hysteresis gap before triggering folding summarization
    context_hysteresis_tokens: int = Field(default=1024, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LOCALAPI_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("allowed_exts", mode="before")
    @classmethod
    def _parse_allowed_exts(cls, v: object) -> object:
        if isinstance(v, str):
            parts = [p.strip().lower() for p in v.split(",") if p.strip()]
            norm = [p if p.startswith(".") else f".{p}" for p in parts]
            return norm
        if isinstance(v, list):
            return [str(p).lower() if str(p).startswith(".") else f".{str(p).lower()}" for p in v]
        return v

    @field_validator("app_base_url", mode="before")
    @classmethod
    def _norm_base_url(cls, v: object) -> str:
        if not v:
            return "http://127.0.0.1:8080"
        s = str(v).strip().rstrip('/')
        return s


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance.

    Also honor LOCALAI_MAX_UPLOAD_MB and LOCALAI_ALLOWED_EXTS as overrides
    for DX compatibility with UI prompts.
    """
    overrides = {}
    if "LOCALAI_MAX_UPLOAD_MB" in os.environ:
        try:
            overrides["max_upload_mb"] = int(os.environ["LOCALAI_MAX_UPLOAD_MB"])
        except Exception:
            pass
    if "LOCALAI_ALLOWED_EXTS" in os.environ:
        overrides["allowed_exts"] = os.environ["LOCALAI_ALLOWED_EXTS"]
    return Settings(**overrides)


# Optional module-level singleton for direct import in UI code
settings = get_settings()
