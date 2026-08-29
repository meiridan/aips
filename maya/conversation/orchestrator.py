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
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya import runtime_cache
from maya.companions.commitments import CommitmentService
from maya.companions.templates import get_template
from maya.conversation import prompt_log, response_length
from maya.conversation.moment_analyzer import (
    MomentAnalysis,
    MomentAnalyzer,
    default_moment,
)
from maya.conversation.prompt_builder import (
    SYSTEM_PROMPT_TEMPLATE,
    build_basic,
    build_phase3,
    count_tokens,
    format_memories,
)
from maya.db.models import Companion, Message
from maya.db.session import get_sessionmaker
from maya.emotional.service import EmotionalService
from maya.llm.service import LLMService
from maya.logging import get_logger
from maya.memory.service import MemoryService
from maya.relationship.service import RelationshipService

log = get_logger("maya.orchestrator")

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

    turn_id: str
    user_id: uuid.UUID
    companion_id: uuid.UUID
    companion_name: str
    user_message: str
    prompt: list[dict]
    moment_task: asyncio.Task
    on_step: StepCallback | None
    max_tokens: int = 800
    spans: dict[str, int] = field(default_factory=dict)


async def _timed(spans: dict[str, int], name: str, coro: Coroutine[Any, Any, Any]) -> Any:
    """Await `coro`, recording its wall time into spans[f"{name}_ms"]."""
    t = time.perf_counter()
    try:
        return await coro
    finally:
        spans[f"{name}_ms"] = int((time.perf_counter() - t) * 1000)


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
        on_reply_done: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> str:
        """Non-streaming turn (CLI / tests / Telegram). Collects the full reply.

        `on_reply_done` (if given) is invoked the instant the reply is ready —
        BEFORE post-processing — so a channel can deliver it without waiting on
        bookkeeping. Post-processing is still awaited before returning
        (Decision 2: no loss on disconnect)."""
        spans: dict[str, int] = {}
        t_prep = time.perf_counter()
        ctx = await self._prepare(user_id, companion_id, content, on_step, spans)
        spans["prepare_ms"] = int((time.perf_counter() - t_prep) * 1000)

        await _emit(on_step, "llm", "🤖 Calling LLM (main tier)", {"messages": len(ctx.prompt)})
        t_llm = time.perf_counter()
        response = await self.llm.chat(
            ctx.prompt, model_tier=self._default_tier, max_tokens=ctx.max_tokens
        )
        spans["llm_ms"] = int((time.perf_counter() - t_llm) * 1000)
        await _emit(on_step, "llm", "✅ LLM response received", {"preview": response[:120]})

        # Deliver the reply before bookkeeping runs (channels that pass this get
        # the latency win; the reply is still saved/post-processed below).
        if on_reply_done is not None:
            res = on_reply_done(response)
            if inspect.isawaitable(res):
                await res

        t_fin = time.perf_counter()
        await self._finalize(ctx, response)
        spans["finalize_ms"] = int((time.perf_counter() - t_fin) * 1000)
        log.info("turn_timing", turn_id=ctx.turn_id, channel="sync", **spans)
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
        spans: dict[str, int] = {}
        t_prep = time.perf_counter()
        ctx = await self._prepare(user_id, companion_id, content, on_step, spans)
        spans["prepare_ms"] = int((time.perf_counter() - t_prep) * 1000)

        await _emit(on_step, "llm", "🤖 Streaming LLM (main tier)", {"messages": len(ctx.prompt)})
        chunks: list[str] = []
        t_llm = time.perf_counter()
        first = True
        async for piece in self.llm.chat_stream(
            ctx.prompt, model_tier=self._default_tier, max_tokens=ctx.max_tokens
        ):
            if first:
                spans["ttft_ms"] = int((time.perf_counter() - t_llm) * 1000)
                first = False
            chunks.append(piece)
            yield piece
        spans["stream_total_ms"] = int((time.perf_counter() - t_llm) * 1000)
        response = "".join(chunks)
        await _emit(on_step, "llm", "✅ Stream complete", {"chars": len(response)})

        # Signal reply-complete to the caller before bookkeeping runs.
        if on_reply_done is not None:
            res = on_reply_done(response)
            if inspect.isawaitable(res):
                await res

        t_fin = time.perf_counter()
        await self._finalize(ctx, response)
        spans["finalize_ms"] = int((time.perf_counter() - t_fin) * 1000)
        log.info("turn_timing", turn_id=ctx.turn_id, channel="web", **spans)

    async def _prepare(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
        on_step: StepCallback | None,
        spans: dict[str, int],
    ) -> _TurnCtx:
        """Steps 1–4: save user msg, gather context, kick off moment analysis
        concurrently, and build the prompt. Moment is OFF the critical path —
        the main LLM call starts with neutral guidance while the analyzer runs
        in parallel and feeds post-processing (emotional state).

        The user-message save, every context read, and the user-name lookup all
        run in ONE gather so the slowest leg (the embedding + pgvector search)
        hides the DB round trips. The companion load is sequential ahead of the
        gather only because emotional.get needs its baseline — and it is cached,
        so it is ~0ms after the first turn."""
        turn_id = uuid.uuid4().hex[:8]
        await _emit(on_step, "step", "📥 Received user message", {"content": content[:100]})

        # Companion first: emotional.get needs its baseline. Cached → ~0ms.
        t = time.perf_counter()
        companion = await self._load_companion(companion_id)
        spans["companion_ms"] = int((time.perf_counter() - t) * 1000)
        baseline = get_template(companion.template_id).baseline_emotional if companion else {}

        # One gather: save + all context reads + user_name, fully overlapped.
        t = time.perf_counter()
        (
            _saved,
            memories,
            emotional,
            relationship,
            commitments,
            recent,
            user_name,
        ) = await asyncio.gather(
            _timed(spans, "save", self._save_user_message(companion_id, user_id, content)),
            _timed(spans, "memory",
                   self.memory.search_relevant(content, user_id, companion_id, MEMORY_LIMIT)),
            _timed(spans, "emotional", self.emotional.get(companion_id, baseline=baseline)),
            _timed(spans, "relationship", self.relationship.get(companion_id, user_id)),
            _timed(spans, "commitments", self.commitments.get_recent(companion_id, limit=20)),
            _timed(spans, "recent", self._recent_messages_own(companion_id, RECENT_LIMIT)),
            _timed(spans, "user_name", self._user_name(user_id)),
        )
        spans["gather_ms"] = int((time.perf_counter() - t) * 1000)
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
        length_level = response_length.normalize(
            getattr(companion, "response_length", response_length.DEFAULT)
        )
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
            response_length=length_level,
        )
        # The save runs concurrently with the recent-messages query, so the new
        # user turn may or may not be in `recent`. Guarantee it is the final
        # message exactly once (ordering is no longer load-bearing).
        if not (prompt and prompt[-1]["role"] == "user" and prompt[-1]["content"] == content):
            prompt.append({"role": "user", "content": content})
        await _emit(on_step, "step", "🔨 Built Phase-3 prompt", {"messages": len(prompt)})

        # The living log: what was actually sent, not what show-prompt predicts.
        # Token counting is not free, so only pay for it when the log is on.
        if prompt_log.log_path() is not None:
            prompt_log.record_prompt(
                turn_id=turn_id,
                companion_name=companion.name if companion else "Maya",
                prompt=prompt,
                tokens=count_tokens(prompt[0]["content"]),
            )
        return _TurnCtx(
            turn_id=turn_id,
            user_id=user_id,
            companion_id=companion_id,
            companion_name=companion.name if companion else "Maya",
            user_message=content,
            prompt=prompt,
            moment_task=moment_task,
            on_step=on_step,
            max_tokens=response_length.max_tokens_for(length_level),
            spans=spans,
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
        prompt_log.record_reply(turn_id=ctx.turn_id, reply=response)
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

    async def _save_user_message(
        self, companion_id: uuid.UUID, user_id: uuid.UUID, content: str
    ) -> None:
        """Own session, committed — safe to run concurrently in the prepare gather."""
        async with self._sessionmaker() as session:
            await self._save_message(session, companion_id, user_id, "user", content)
            await session.commit()

    async def _recent_messages_own(
        self, companion_id: uuid.UUID, limit: int
    ) -> list[Message]:
        async with self._sessionmaker() as session:
            return await self._recent_messages(session, companion_id, limit)

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
        cached = runtime_cache.get_companion(companion_id)
        if cached is not None:
            return cached
        async with self._sessionmaker() as session:
            comp = await session.get(Companion, companion_id)
            if comp is not None:
                session.expunge(comp)
                runtime_cache.set_companion(companion_id, comp)
            return comp

    async def _user_name(self, user_id: uuid.UUID) -> str:
        cached = runtime_cache.get_user_name(user_id)
        if cached is not None:
            return cached
        from maya.db.models import User

        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            name = user.name if user else "him"
            runtime_cache.set_user_name(user_id, name)
            return name

    @staticmethod
    def _hours_since(last: datetime | None) -> float:
        if last is None:
            return 0.0
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - last).total_seconds() / 3600.0)


# Keep build_basic referenced for back-compat imports.
_ = build_basic
