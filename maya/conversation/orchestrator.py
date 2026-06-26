"""Phase 3 orchestrator: the full companion loop (§P3.10).

Context gather → moment analysis → rich prompt → main LLM call → reply, then
synchronous post-processing (Decision 2: await-after-send — the reply is
produced first, bookkeeping is awaited before the next turn so nothing is lost
on disconnect; we deliberately avoid the spec's fire-and-forget create_task).

A single optional `on_step` callback emits structured progress events. The web
debug panel subscribes to it — one code path, no DebugOrchestrator duplication.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.companions.commitments import CommitmentService
from maya.companions.templates import get_template
from maya.conversation.moment_analyzer import (
    MomentAnalysis,
    MomentAnalyzer,
    default_moment,
)
from maya.conversation.prompt_builder import (
    SYSTEM_PROMPT_TEMPLATE,
    build_basic,
    build_phase3,
    format_memories,
)
from maya.db.models import Companion, Message
from maya.db.session import get_sessionmaker
from maya.emotional.service import EmotionalService
from maya.llm.service import LLMService
from maya.memory.service import MemoryService
from maya.relationship.service import RelationshipService

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

# Above this intensity a turn is logged as a significant relationship event.
SIGNIFICANT_INTENSITY = 0.8

StepCallback = Callable[[str, str, dict], Awaitable[None] | None]


@dataclass
class _TurnCtx:
    """Everything carried from prompt-prep into reply finalization."""

    user_id: uuid.UUID
    companion_id: uuid.UUID
    companion_name: str
    user_message: str
    prompt: list[dict]
    moment_task: asyncio.Task
    on_step: StepCallback | None


async def _emit(on_step: StepCallback | None, category: str, label: str, data: dict) -> None:
    if on_step is None:
        return
    try:
        result = on_step(category, label, data)
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - debug emission must never break the loop
        pass


class Orchestrator:
    def __init__(
        self,
        llm: LLMService | None = None,
        memory: MemoryService | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        emotional: EmotionalService | None = None,
        relationship: RelationshipService | None = None,
        commitments: CommitmentService | None = None,
        moment_analyzer: MomentAnalyzer | None = None,
        default_tier: str = "main",
    ) -> None:
        self.llm = llm or LLMService()
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self.memory = memory or MemoryService(
            llm=self.llm, sessionmaker=self._sessionmaker
        )
        self.emotional = emotional or EmotionalService(self._sessionmaker)
        self.relationship = relationship or RelationshipService(self._sessionmaker)
        self.commitments = commitments or CommitmentService(self._sessionmaker, llm=self.llm)
        self.moment_analyzer = moment_analyzer or MomentAnalyzer(self.llm)
        self._default_tier = default_tier

    async def handle_message(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
        on_step: StepCallback | None = None,
    ) -> str:
        """Non-streaming turn (CLI / tests). Collects the full reply."""
        ctx = await self._prepare(user_id, companion_id, content, on_step)
        await _emit(on_step, "llm", "🤖 Calling LLM (main tier)", {"messages": len(ctx.prompt)})
        response = await self.llm.chat(ctx.prompt, model_tier=self._default_tier)
        await _emit(on_step, "llm", "✅ LLM response received", {"preview": response[:120]})
        await self._finalize(ctx, response)
        return response

    async def stream_message(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
        on_step: StepCallback | None = None,
        on_reply_done: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming turn: yields reply chunks as they arrive (web UI).

        `on_reply_done` (if given) is invoked the instant the last chunk is
        yielded — BEFORE post-processing — so the UI can re-enable input and
        mark the reply complete without waiting on bookkeeping. Post-processing
        then runs and is still awaited before the generator returns (Decision 2:
        no loss on disconnect).
        """
        ctx = await self._prepare(user_id, companion_id, content, on_step)
        await _emit(on_step, "llm", "🤖 Streaming LLM (main tier)", {"messages": len(ctx.prompt)})
        chunks: list[str] = []
        async for piece in self.llm.chat_stream(ctx.prompt, model_tier=self._default_tier):
            chunks.append(piece)
            yield piece
        response = "".join(chunks)
        await _emit(on_step, "llm", "✅ Stream complete", {"chars": len(response)})

        # Signal reply-complete to the caller before bookkeeping runs.
        if on_reply_done is not None:
            res = on_reply_done(response)
            if inspect.isawaitable(res):
                await res

        await self._finalize(ctx, response)

    async def _prepare(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
        on_step: StepCallback | None,
    ) -> _TurnCtx:
        """Steps 1–4: save user msg, gather context, kick off moment analysis
        concurrently, and build the prompt. Moment is OFF the critical path —
        the main LLM call starts with neutral guidance while the analyzer runs
        in parallel and feeds post-processing (emotional state)."""
        await _emit(on_step, "step", "📥 Received user message", {"content": content[:100]})

        # 1. Save user message.
        async with self._sessionmaker() as session:
            await self._save_message(session, companion_id, user_id, "user", content)
            await session.commit()

        # 2. Gather context in parallel.
        companion = await self._load_companion(companion_id)
        baseline = get_template(companion.template_id).baseline_emotional if companion else {}
        async with self._sessionmaker() as session:
            recent_task = self._recent_messages(session, companion_id, RECENT_LIMIT)
            (
                memories,
                emotional,
                relationship,
                commitments,
                recent,
            ) = await asyncio.gather(
                self.memory.search_relevant(content, user_id, companion_id, MEMORY_LIMIT),
                self.emotional.get(companion_id, baseline=baseline),
                self.relationship.get(companion_id, user_id),
                self.commitments.get_recent(companion_id, limit=20),
                recent_task,
            )
        hours_since = self._hours_since(getattr(relationship, "last_interaction_at", None))
        await _emit(on_step, "memory", f"✅ Gathered context ({len(memories)} memories)", {
            "memories": len(memories),
            "stage": getattr(relationship, "stage", "?"),
            "feelings": getattr(emotional, "feelings", {}),
        })

        # 3. Moment analysis — concurrent, not awaited here (off critical path).
        moment_task = asyncio.create_task(
            self.moment_analyzer.analyze(content, emotional, relationship, recent)
        )

        # 4. Build the rich prompt with neutral moment guidance so the main call
        # can start immediately. The real moment refines emotional state later.
        user_name = await self._user_name(user_id)
        prompt = build_phase3(
            companion=companion,
            memories=memories,
            emotional=emotional,
            relationship=relationship,
            commitments=commitments,
            moment=default_moment(),
            recent_msgs=recent,
            user_name=user_name,
            hours_since_last=hours_since,
        )
        await _emit(on_step, "step", "🔨 Built Phase-3 prompt", {"messages": len(prompt)})
        return _TurnCtx(
            user_id=user_id,
            companion_id=companion_id,
            companion_name=companion.name if companion else "Maya",
            user_message=content,
            prompt=prompt,
            moment_task=moment_task,
            on_step=on_step,
        )

    async def _finalize(self, ctx: _TurnCtx, response: str) -> None:
        """Save the assistant reply, then run post-processing (awaited after the
        reply is already produced / displayed)."""
        async with self._sessionmaker() as session:
            assistant_msg = await self._save_message(
                session, ctx.companion_id, ctx.user_id, "assistant", response
            )
            assistant_msg_id = assistant_msg.id
            await session.commit()
        await _emit(ctx.on_step, "step", "✅ Assistant response saved", {})

        moment = await ctx.moment_task  # the real moment, computed in parallel
        await _emit(ctx.on_step, "step", f"🔍 Moment: {moment.moment_type}", {
            "moment_type": moment.moment_type,
            "intensity": moment.emotional_intensity,
            "priority": moment.character_priority,
        })
        await self._post_process(
            user_id=ctx.user_id,
            companion_id=ctx.companion_id,
            companion_name=ctx.companion_name,
            user_message=ctx.user_message,
            assistant_message=response,
            assistant_msg_id=assistant_msg_id,
            moment=moment,
            on_step=ctx.on_step,
        )
        await _emit(ctx.on_step, "step", "🎉 Message handling complete", {})

    async def _post_process(
        self,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        companion_name: str,
        user_message: str,
        assistant_message: str,
        assistant_msg_id: uuid.UUID,
        moment: MomentAnalysis,
        on_step: StepCallback | None,
    ) -> None:
        """Update every store after the reply (Decision 2: awaited, not detached)."""
        results = await asyncio.gather(
            self.memory.extract_and_store(
                user_id=user_id,
                companion_id=companion_id,
                user_message=user_message,
                assistant_message=assistant_message,
            ),
            self.emotional.update_after_message(companion_id, moment.emotional_delta),
            self.relationship.increment_interaction(companion_id),
            self.commitments.extract_from_message(
                companion_id, companion_name, assistant_message,
                source_message_id=assistant_msg_id,
            ),
            return_exceptions=True,
        )
        facts = results[0] if not isinstance(results[0], Exception) else []
        new_commits = results[3] if not isinstance(results[3], Exception) else []
        await _emit(on_step, "memory", "💡 Post-processing applied", {
            "new_facts": facts if isinstance(facts, list) else [],
            "new_commitments": len(new_commits) if isinstance(new_commits, list) else 0,
        })

        # Log a significant event for high-intensity moments.
        if moment.emotional_intensity > SIGNIFICANT_INTENSITY:
            await self.relationship.log_event(
                companion_id=companion_id,
                event_type="emotional_moment",
                summary=f"Intense {moment.moment_type}",
                impact={"intimacy_delta": 1},
            )

        # Maybe transition stage.
        new_stage = await self.relationship.evaluate_stage_transition(companion_id)
        if new_stage is not None:
            await _emit(on_step, "step", f"💞 Stage → {new_stage.value}", {
                "stage": new_stage.value,
            })

    # ── helpers ──────────────────────────────────────────────────────────

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

    async def _load_companion(self, companion_id: uuid.UUID) -> Companion | None:
        async with self._sessionmaker() as session:
            comp = await session.get(Companion, companion_id)
            if comp is not None:
                session.expunge(comp)
            return comp

    async def _user_name(self, user_id: uuid.UUID) -> str:
        from maya.db.models import User

        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            return user.name if user else "him"

    @staticmethod
    def _hours_since(last: datetime | None) -> float:
        if last is None:
            return 0.0
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - last).total_seconds() / 3600.0)


# Keep build_basic referenced for back-compat imports.
_ = build_basic
