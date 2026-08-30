"""Telegram → orchestrator bridge.

The chat_id is the account key for this channel: it both addresses replies and
picks the identity, via `users.telegram_chat_id`. Each chat therefore gets its
own companion and its own memory — the same isolation the web channel gets from
its session cookie.

Telegram has no creation wizard, so a first-time chat runs genesis immediately
rather than waiting for a spec. See maya.companions.singleton.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.billing import entitlements
from maya.companions.settings import set_response_length
from maya.companions.singleton import resolve_by_telegram_chat
from maya.config import get_settings
from maya.conversation import response_length
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

        # This chat's own Maya, created on first contact.
        uid, cid, created, first_message = await resolve_by_telegram_chat(
            self._sessionmaker, chat_id=int(chat_id)
        )

        if created and first_message:
            await self.client.send_message(int(chat_id), first_message)

        if text.strip() == "/start":
            if not created:
                await self.client.send_message(int(chat_id), "Hey — I'm here. What's on your mind?")
            return  # greeting already covers a brand-new companion

        if text.strip().lower().startswith("/length"):
            parts = text.split(maxsplit=1)
            level = response_length.parse(parts[1]) if len(parts) > 1 else None
            if level is None:
                await self.client.send_message(
                    int(chat_id), "Usage: /length short|medium|long (or 1|2|3)"
                )
            else:
                await set_response_length(self._sessionmaker, cid, level)
                await self.client.send_message(
                    int(chat_id), f"Reply length set to {response_length.label(level)}."
                )
            return

        # Same entitlement gate as the web channel — one budget per account,
        # whichever way they reach her.
        if await entitlements.quota_exceeded(self._sessionmaker, uid):
            await self.client.send_message(
                int(chat_id),
                "הגעת למכסת ההודעות היומית. אפשר להמשיך מחר, או לשדרג למנוי.",
            )
            return

        await self.client.send_chat_action(int(chat_id), "typing")
        sent = {"reply": False}

        async def deliver(reply: str) -> None:
            # Fires the instant the reply is ready — BEFORE post-processing — so
            # the user isn't waiting on bookkeeping (memory extract, stage eval…).
            sent["reply"] = True
            await self.client.send_message(int(chat_id), reply)

        try:
            await self.orchestrator.handle_message(uid, cid, text, on_reply_done=deliver)
        except Exception as exc:  # noqa: BLE001 - never crash the webhook
            log.error("telegram_turn_failed", chat_id=chat_id, error=str(exc))
            # Only apologize if the reply never went out; a post-processing
            # failure after delivery must not spam a second message.
            if not sent["reply"]:
                await self.client.send_message(
                    int(chat_id), "Sorry, I glitched for a second. Say that again?"
                )


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
