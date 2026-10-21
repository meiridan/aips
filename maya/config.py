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

    # Auth: how long a login cookie stays valid, refreshed on use.
    session_ttl_days: int = 30

    # Google OAuth (optional — unset disables the "Continue with Google" path).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Defaults to {public_base_url}/auth/google/callback; set explicitly only
    # when the public URL and the registered redirect URI differ.
    google_redirect_uri: str = ""

    # Transactional email (optional — unset logs the link instead of sending,
    # which is what local dev and the tests rely on).
    resend_api_key: str = ""
    mail_from: str = "Maya <onboarding@resend.dev>"
    # Defaults to {public_base_url}/reset-password.
    password_reset_url_base: str = ""

    # Stripe (optional — unset makes the checkout/portal endpoints answer 503
    # while the plans and current status still render).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus_monthly: str = ""
    stripe_price_plus_yearly: str = ""

    # Free-tier daily message allowance, enforced server-side on both channels.
    free_daily_message_limit: int = 30

    # Group chat (the account's companion + Lila, maya/conversation/group.py).
    group_chat_enabled: bool = True
    # Hard ceiling on companion messages per user message, director follow-ups
    # included — the backstop against two models talking forever on our bill.
    # In "moderated" talk mode this is the turn's ceiling.
    group_max_ai_messages_per_turn: int = 4
    # Moderated talk: they go back and forth at least this many lines before the
    # director may hand the floor back.
    group_moderated_min_messages: int = 3
    # Free talk: they keep talking until the user writes — or this many lines,
    # so a room left open does not run up the bill.
    group_free_talk_max_messages: int = 20
    # Off: nobody follows up past the moderated minimum on her own.
    group_director_enabled: bool = True

    # Dev-only: treat every unauthenticated request as a fixed local account, so
    # the wizard and chat can be exercised without a login. Ignored unless
    # ENVIRONMENT=local, so setting it in a deployed env cannot open the app up.
    dev_autologin: bool = False

    # Single-user mode: no login screen anywhere, every request resolves to one
    # account. Unlike dev_autologin this is deliberately NOT gated on
    # ENVIRONMENT — the deployed instance is open too, which is the point while
    # the login flow is parked. Set SINGLE_USER=0 to get the login screen back.
    single_user: bool = True
    # Which row single-user mode lands on. Unset = find-or-create the sentinel
    # account in maya/auth/deps.py.
    maya_single_user_id: str | None = None

    # Active context used by the CLI (export MAYA_USER_ID / MAYA_COMPANION_ID).
    maya_user_id: str | None = None
    maya_companion_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
