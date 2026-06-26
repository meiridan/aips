"""Commitments service (§P3.6) — companion self-consistency store.

3b ships CRUD (`add`, `get_recent`). 3e adds LLM extraction
(`extract_from_message`) — cheap call pulling identity claims, promises,
opinions, and preferences out of the companion's own replies.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.db.models import CompanionCommitment
from maya.db.session import get_sessionmaker
from maya.llm.service import LLMService
from maya.logging import get_logger

log = get_logger("maya.commitments")

EXTRACTION_PROMPT = """The companion {name} just said this to the person she's talking to:

"{message}"

What did she reveal about HERSELF — identity claims, promises, opinions, or \
preferences? Only genuine first-person self-statements (NOT facts about him).

Return JSON:
{{"commitments": [
  {{"content": "I ...", "commitment_type": "identity|preference|opinion|promise", "importance": 0.0-1.0}}
]}}

Return an empty list if she revealed nothing about herself."""

_VALID_TYPES = {"identity", "preference", "opinion", "promise"}


class CommitmentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        llm: LLMService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self.llm = llm or LLMService()

    async def add(
        self,
        companion_id: uuid.UUID,
        content: str,
        commitment_type: str,
        importance: float = 0.5,
        source_message_id: uuid.UUID | None = None,
    ) -> CompanionCommitment:
        async with self._sessionmaker() as session:
            c = CompanionCommitment(
                companion_id=companion_id,
                content=content,
                commitment_type=commitment_type,
                importance=importance,
                source_message_id=source_message_id,
            )
            session.add(c)
            await session.commit()
            session.expunge(c)
            return c

    async def get_recent(
        self, companion_id: uuid.UUID, limit: int = 20
    ) -> list[CompanionCommitment]:
        """Most-important active commitments first, capped at `limit`."""
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(CompanionCommitment)
                    .where(
                        CompanionCommitment.companion_id == companion_id,
                        CompanionCommitment.status == "active",
                    )
                    .order_by(
                        CompanionCommitment.importance.desc(),
                        CompanionCommitment.created_at.desc(),
                    )
                    .limit(limit)
                )
            ).all()
            for r in rows:
                session.expunge(r)
            return list(rows)

    async def extract_from_message(
        self,
        companion_id: uuid.UUID,
        companion_name: str,
        message_content: str,
        source_message_id: uuid.UUID | None = None,
    ) -> list[CompanionCommitment]:
        """Cheap LLM pass: pull the companion's self-statements and store them.

        Fail-safe: any error returns [] without touching state — never blocks
        the chat loop (called from post-processing).
        """
        prompt = EXTRACTION_PROMPT.format(name=companion_name, message=message_content)
        try:
            data = await self.llm.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model_tier="cheap",
                purpose="commitment_extraction",
                max_tokens=400,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("commitment_extract_failed", error=str(exc))
            return []

        out: list[CompanionCommitment] = []
        for c in data.get("commitments", []) or []:
            content = str(c.get("content", "")).strip()
            if not content:
                continue
            ctype = str(c.get("commitment_type", "identity"))
            if ctype not in _VALID_TYPES:
                ctype = "identity"
            try:
                importance = float(c.get("importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5
            out.append(
                await self.add(
                    companion_id=companion_id,
                    content=content,
                    commitment_type=ctype,
                    importance=max(0.0, min(1.0, importance)),
                    source_message_id=source_message_id,
                )
            )
        return out
