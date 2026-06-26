"""Telegram → orchestrator bridge.

Maps a Telegram chat to a private (User, Companion) pair and routes inbound
text through the shared Orchestrator, exactly like the CLI/web channels. New
chats are brought to life with genesis on first contact.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.companions.genesis import run_genesis
from maya.config import get_settings
from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, User
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

    async def get_or_create_for_chat(
        self,
        chat_id: int,
        first_name: str | None = None,
        username: str | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID, bool, str | None]:
        """Return (user_id, companion_id, created, first_message).

        `created` is True only when this chat had no user yet; in that case the
        companion has been run through genesis and `first_message` is its opener.
        """
        sm = self._sessionmaker
        async with sm() as session:
            user = (
                await session.execute(
                    select(User).where(User.telegram_chat_id == chat_id)
                )
            ).scalar_one_or_none()

            if user is not None:
                companion = (
                    await session.execute(
                        select(Companion)
                        .where(Companion.user_id == user.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if companion is not None:
                    return user.id, companion.id, False, None
                # User without a companion (unexpected) — create one below.
                companion = Companion(user_id=user.id, name="Maya", template_id="flirt")
                session.add(companion)
                await session.commit()
                companion_id = companion.id
            else:
                name = first_name or username or f"tg-{chat_id}"
                user = User(
                    name=name,
                    description=f"Telegram user @{username}" if username else None,
                    telegram_chat_id=chat_id,
                )
                session.add(user)
                await session.flush()
                companion = Companion(user_id=user.id, name="Maya", template_id="flirt")
                session.add(companion)
                await session.commit()
                user_id, companion_id = user.id, companion.id
                # Bring the companion to life. Genesis persists the opener as the
                # first assistant message; we surface its text to send back.
                result = await run_genesis(companion_id, sessionmaker=sm)
                log.info("telegram_user_created", chat_id=chat_id, user_id=str(user_id))
                return user_id, companion_id, True, result.first_message

            return user.id, companion_id, False, None

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

        sender = message.get("from") or {}
        uid, cid, created, first_message = await self.get_or_create_for_chat(
            int(chat_id),
            first_name=sender.get("first_name"),
            username=sender.get("username"),
        )

        if created and first_message:
            await self.client.send_message(int(chat_id), first_message)

        if text.strip() == "/start":
            if not created:
                await self.client.send_message(int(chat_id), "Hey — I'm here. What's on your mind?")
            return  # greeting already covers a brand-new chat

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
