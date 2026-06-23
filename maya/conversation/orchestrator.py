"""Phase 2 orchestrator: chat loop WITH memory layer. Spec §P2.2."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.conversation.prompt_builder import (
    SYSTEM_PROMPT_TEMPLATE,
    build_basic,
    format_memories,
)
from maya.db.models import Message
from maya.db.session import get_sessionmaker
from maya.llm.service import LLMService
from maya.memory.service import MemoryService

# Re-export for callers (web.py) that imported from here previously.
__all__ = [
    "Orchestrator",
    "SYSTEM_PROMPT_TEMPLATE",
    "_format_memories",
]

# Backwards-compat alias for the old private helper.
_format_memories = format_memories

RECENT_LIMIT = 30  # Maya sees her own recent responses, can correlate
MEMORY_LIMIT = 15


class Orchestrator:
    def __init__(
        self,
        llm: LLMService | None = None,
        memory: MemoryService | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        default_tier: str = "main",
    ) -> None:
        self.llm = llm or LLMService()
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self.memory = memory or MemoryService(
            llm=self.llm, sessionmaker=self._sessionmaker
        )
        self._default_tier = default_tier

    async def handle_message(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
    ) -> str:
        async with self._sessionmaker() as session:
            # 1. Save user message
            await self._save_message(session, companion_id, user_id, "user", content)
            await session.commit()

            # 2. Search memory + get recent messages in parallel
            memories_task = self.memory.search_relevant(
                query=content,
                user_id=user_id,
                companion_id=companion_id,
                limit=MEMORY_LIMIT,
            )
            recent_task = self._recent_messages(session, companion_id, RECENT_LIMIT)
            memories, recent = await asyncio.gather(memories_task, recent_task)

            # 3. Build prompt (system prompt with score-tagged memories + recent msgs)
            prompt = build_basic(memories=memories, recent_msgs=recent)

            # 4. Call LLM
            response = await self.llm.chat(prompt, model_tier=self._default_tier)

            # 5. Save assistant message
            await self._save_message(
                session, companion_id, user_id, "assistant", response
            )
            await session.commit()

        # 6. Extract & store new facts synchronously so no fact falls into the
        # "no-man's-land" between context window and Mem0.  Adds ~1-3s per turn
        # but prevents information loss when RECENT_LIMIT pushes facts out of
        # context before async extraction completes.
        await self.memory.extract_and_store(
            user_id=user_id,
            companion_id=companion_id,
            user_message=content,
            assistant_message=response,
        )

        return response

    async def _save_message(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        content: str,
    ) -> Message:
        msg = Message(
            companion_id=companion_id, user_id=user_id, role=role, content=content
        )
        session.add(msg)
        await session.flush()
        return msg

    async def _recent_messages(
        self, session: AsyncSession, companion_id: uuid.UUID, limit: int
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.companion_id == companion_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list((await session.scalars(stmt)).all())
        rows.reverse()  # back to chronological order for the prompt
        return rows
