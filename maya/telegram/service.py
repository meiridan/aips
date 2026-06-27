"""Telegram → orchestrator bridge.

Single-user app: every Telegram chat talks to the ONE shared Maya (same
companion + memory as the web UI). The chat_id is used only to address replies,
not to pick an identity. See maya.companions.singleton.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.companions.singleton import resolve_singleton
from maya.config import get_settings
from maya.conversation.orchestrator import Orchestrator
from maya.db.session import get_sessionmaker
from maya.logging import get_logger
from maya.telegram.client import TelegramClient

log = get_logger("maya.telegram")


class TelegramService:
    def __init__(
        self,
        client: TelegramClient,
        orchestrator: Orchestrator | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.client = client
        self._sessionmaker = sessionmaker or get_sessionmaker()
        # One shared orchestrator (built once) — same rationale as the CLI REPL:
        # keeps the async engine's connections bound to one loop.
        self.orchestrator = orchestrator or Orchestrator()

    async def handle_update(self, update: dict) -> None:
        """Process a single Telegram update. Non-text/non-message updates ignored."""
        message = update.get("message")
        if not isinstance(message, dict):
            return  # edited_message, callback_query, etc. — not supported
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")
        if chat_id is None or not isinstance(text, str) or not text.strip():
            return

        # Single shared Maya — same companion as the web UI.
        uid, cid, created, first_message = await resolve_singleton(self._sessionmaker)

        if created and first_message:
            await self.client.send_message(int(chat_id), first_message)

        if text.strip() == "/start":
            if not created:
                await self.client.send_message(int(chat_id), "Hey — I'm here. What's on your mind?")
            return  # greeting already covers a brand-new companion

        await self.client.send_chat_action(int(chat_id), "typing")
        try:
            reply = await self.orchestrator.handle_message(uid, cid, text)
        except Exception as exc:  # noqa: BLE001 - never crash the webhook
            log.error("telegram_turn_failed", chat_id=chat_id, error=str(exc))
            await self.client.send_message(
                int(chat_id), "Sorry, I glitched for a second. Say that again?"
            )
            return
        await self.client.send_message(int(chat_id), reply)


_service: TelegramService | None = None


def get_telegram_service() -> TelegramService | None:
    """Lazily build the channel from settings. None when no bot token configured."""
    global _service
    if _service is not None:
        return _service
    settings = get_settings()
    if not settings.telegram_bot_token:
        return None
    verify = settings.environment == "prod"
    client = TelegramClient(settings.telegram_bot_token, verify=verify)
    _service = TelegramService(client)
    return _service
