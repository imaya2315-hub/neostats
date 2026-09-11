"""
Centralised application configuration.

Everything that could vary between local/dev/production environments is
read from environment variables (never hardcoded), with sane local
defaults so the app also runs out-of-the-box for evaluation.
"""
from __future__ import annotations

import os
from functools import lru_cache


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: list[str]) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


class Settings:
    # --- General ---
    APP_NAME: str = os.getenv("APP_NAME", "Document Intelligence Platform")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", os.path.join(os.getcwd(), "logs"))

    # --- CORS ---
    CORS_ORIGINS: list[str] = _get_list("CORS_ORIGINS", ["*"])

    # --- Storage / uploads ---
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "3"))
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))

    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///" + os.path.join(os.getcwd(), "data", "documents.db")
    )

    # --- LLM / extraction ---
    # Any provider can be used; Anthropic is the default here. The key is
    # read from the environment only and is never committed to source.
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "900"))
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    # --- Financial validation ---
    # A value passes reconciliation if the absolute variance is within the
    # larger of an absolute floor and a percentage of the reported value.
    VALIDATION_ABS_TOLERANCE: float = float(os.getenv("VALIDATION_ABS_TOLERANCE", "1.0"))
    VALIDATION_PCT_TOLERANCE: float = float(os.getenv("VALIDATION_PCT_TOLERANCE", "0.01"))

    def __init__(self) -> None:
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.LOG_DIR, exist_ok=True)
        db_path = self.DATABASE_URL.replace("sqlite:///", "")
        if self.DATABASE_URL.startswith("sqlite") and db_path:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
