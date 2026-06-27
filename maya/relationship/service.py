"""Relationship state service (§P3.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.db.models import RelationshipEvent, RelationshipState
from maya.db.session import get_sessionmaker
from maya.relationship.transitions import (
    EventLike,
    Stage,
    TransitionContext,
    next_stage,
)


class RelationshipService:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()

    async def get(
        self, companion_id: uuid.UUID, user_id: uuid.UUID
    ) -> RelationshipState:
        async with self._sessionmaker() as session:
            state = await self._get_or_create(session, companion_id, user_id)
            await session.commit()
            session.expunge(state)
            return state

    async def initialize(
        self, companion_id: uuid.UUID, user_id: uuid.UUID
    ) -> RelationshipState:
        """Create the relationship row at STRANGERS (idempotent)."""
        return await self.get(companion_id, user_id)

    async def increment_interaction(self, companion_id: uuid.UUID) -> None:
        """Bump interaction counter, refresh last_interaction_at + days_known."""
        async with self._sessionmaker() as session:
            state = await self._fetch(session, companion_id)
            if state is None:
                return
            now = datetime.now(UTC)
            state.total_interactions += 1
            state.last_interaction_at = now
            created = state.created_at or now
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            state.days_known = max(state.days_known, (now - created).days)
            await session.commit()

    async def advance_days(self, companion_id: uuid.UUID, n: int = 1) -> None:
        """Advance the *simulated* day counter by `n`.

        The simulator compresses many days into seconds of wall-clock, so the
        real-time `days_known` math in `increment_interaction` never moves.
        This bumps it directly. No-op if the relationship row doesn't exist."""
        async with self._sessionmaker() as session:
            state = await self._fetch(session, companion_id)
            if state is None:
                return
            state.days_known += n
            await session.commit()

    async def get_events(
        self, companion_id: uuid.UUID, limit: int = 200
    ) -> list[RelationshipEvent]:
        """Relationship events, newest first (for snapshots + eval samples)."""
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(RelationshipEvent)
                    .where(RelationshipEvent.companion_id == companion_id)
                    .order_by(RelationshipEvent.occurred_at.desc())
                    .limit(limit)
                )
            ).all()
            for ev in rows:
                session.expunge(ev)
            return list(rows)

    async def log_event(
        self,
        companion_id: uuid.UUID,
        event_type: str,
        summary: str,
        impact: dict | None = None,
    ) -> RelationshipEvent:
        async with self._sessionmaker() as session:
            ev = RelationshipEvent(
                companion_id=companion_id,
                event_type=event_type,
                summary=summary,
                impact=impact or {},
            )
            session.add(ev)
            # Apply intimacy/trust deltas carried on the event, if any.
            if impact:
                state = await self._fetch(session, companion_id)
                if state is not None:
                    di = int(impact.get("intimacy_delta", 0))
                    dt = int(impact.get("trust_delta", 0))
                    if di:
                        state.intimacy_level = max(0, min(10, state.intimacy_level + di))
                    if dt:
                        state.trust_level = max(0, min(10, state.trust_level + dt))
            await session.commit()
            session.expunge(ev)
            return ev

    async def evaluate_stage_transition(
        self, companion_id: uuid.UUID
    ) -> Stage | None:
        """Compute the next stage, persist + log it if one applies."""
        async with self._sessionmaker() as session:
            state = await self._fetch(session, companion_id)
            if state is None:
                return None
            ctx = await self._context(session, state)
            target = next_stage(ctx)
            if target is None or target.value == state.stage:
                return None
            state.stage = target.value
            session.add(
                RelationshipEvent(
                    companion_id=companion_id,
                    event_type="stage_transition",
                    summary=f"Transitioned to {target.value}",
                    impact={},
                )
            )
            await session.commit()
            return target

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    async def _fetch(
        session: AsyncSession, companion_id: uuid.UUID
    ) -> RelationshipState | None:
        return (
            await session.scalars(
                select(RelationshipState).where(
                    RelationshipState.companion_id == companion_id
                )
            )
        ).first()

    @staticmethod
    async def _get_or_create(
        session: AsyncSession, companion_id: uuid.UUID, user_id: uuid.UUID
    ) -> RelationshipState:
        state = (
            await session.scalars(
                select(RelationshipState).where(
                    RelationshipState.companion_id == companion_id,
                    RelationshipState.user_id == user_id,
                )
            )
        ).first()
        if state is None:
            state = RelationshipState(companion_id=companion_id, user_id=user_id)
            session.add(state)
            await session.flush()
        return state

    @staticmethod
    async def _context(
        session: AsyncSession, state: RelationshipState
    ) -> TransitionContext:
        events = (
            await session.scalars(
                select(RelationshipEvent).where(
                    RelationshipEvent.companion_id == state.companion_id
                )
            )
        ).all()
        return TransitionContext(
            stage=state.stage,
            total_interactions=state.total_interactions,
            intimacy_level=state.intimacy_level,
            trust_level=state.trust_level,
            days_known=state.days_known,
            last_interaction_at=state.last_interaction_at,
            events=[
                EventLike(event_type=e.event_type, occurred_at=e.occurred_at)
                for e in events
            ],
        )
