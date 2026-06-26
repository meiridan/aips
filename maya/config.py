"""Application settings loaded from environment / .env (see §4 of the spec)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/maya"
    redis_url: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    xai_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    litellm_log: str = "ERROR"
    environment: str = "local"

    # Telegram bot (optional — unset disables the channel; local dev unaffected).
    telegram_bot_token: str = ""
    # Random string echoed in X-Telegram-Bot-Api-Secret-Token to reject forgeries.
    telegram_webhook_secret: str = ""
    # Public base URL (e.g. Railway domain) used to register the webhook at startup.
    public_base_url: str = ""

    # Active context used by the CLI (export MAYA_USER_ID / MAYA_COMPANION_ID).
    maya_user_id: str | None = None
    maya_companion_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
