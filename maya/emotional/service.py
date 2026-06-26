"""Emotional state service (§P3.4).

Decay is lazy-on-read (Decision 1): `get()` decays feelings toward the
template baseline based on hours since `last_updated`, persists, and returns
the refreshed row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maya.db.models import EmotionalState
from maya.db.session import get_sessionmaker
from maya.emotional.constants import decay_feeling, half_life_for

# Feelings below this after decay are dropped from the dict (noise floor).
FEELING_FLOOR = 0.05


class EmotionalDelta(BaseModel):
    """Moment-driven change to emotional state (produced by the analyzer)."""

    drop_feelings: list[str] = Field(default_factory=list)
    add_feelings: dict[str, float] = Field(default_factory=dict)
    valence_delta: float = 0.0
    arousal_delta: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _baseline_feelings(baseline: dict[str, Any] | None) -> dict[str, float]:
    if not baseline:
        return {}
    return dict(baseline.get("feelings", {}))


class EmotionalService:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()

    async def get(
        self,
        companion_id: uuid.UUID,
        baseline: dict[str, Any] | None = None,
    ) -> EmotionalState:
        """Fetch state, lazily decaying feelings toward `baseline` first."""
        async with self._sessionmaker() as session:
            state = await self._get_or_create(session, companion_id)
            now = datetime.now(UTC)
            hours = self._hours_since(state.last_updated, now)
            if hours > 0 and (state.feelings or baseline):
                self._apply_decay(state, baseline, hours)
                state.last_updated = now
                await session.commit()
            else:
                await session.commit()
            session.expunge(state)
            return state

    async def set_initial(
        self,
        companion_id: uuid.UUID,
        initial_feelings: dict[str, Any],
    ) -> EmotionalState:
        """Seed emotional state from genesis output (valence/arousal/feelings)."""
        async with self._sessionmaker() as session:
            state = await self._get_or_create(session, companion_id)
            state.valence = _clamp(float(initial_feelings.get("valence", 0.0)), -1, 1)
            state.arousal = _clamp(float(initial_feelings.get("arousal", 0.5)), 0, 1)
            state.feelings = {
                k: _clamp(float(v), 0, 1)
                for k, v in dict(initial_feelings.get("feelings", {})).items()
            }
            state.last_updated = datetime.now(UTC)
            await session.commit()
            session.expunge(state)
            return state

    async def update_after_message(
        self,
        companion_id: uuid.UUID,
        delta: EmotionalDelta,
    ) -> EmotionalState:
        """Apply a moment-driven delta: drop, add/boost feelings, shift V/A."""
        async with self._sessionmaker() as session:
            state = await self._get_or_create(session, companion_id)
            feelings = dict(state.feelings or {})
            for name in delta.drop_feelings:
                feelings.pop(name, None)
            for name, val in delta.add_feelings.items():
                feelings[name] = _clamp(float(val), 0, 1)
            state.feelings = feelings
            state.valence = _clamp(state.valence + delta.valence_delta, -1, 1)
            state.arousal = _clamp(state.arousal + delta.arousal_delta, 0, 1)
            state.last_updated = datetime.now(UTC)
            await session.commit()
            session.expunge(state)
            return state

    async def decay(
        self,
        companion_id: uuid.UUID,
        hours_elapsed: float,
        baseline: dict[str, Any] | None,
    ) -> EmotionalState:
        """Explicitly decay by `hours_elapsed` (used by tests / test-clock)."""
        async with self._sessionmaker() as session:
            state = await self._get_or_create(session, companion_id)
            self._apply_decay(state, baseline, hours_elapsed)
            state.last_updated = datetime.now(UTC)
            await session.commit()
            session.expunge(state)
            return state

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _hours_since(last: datetime | None, now: datetime) -> float:
        if last is None:
            return 0.0
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return max(0.0, (now - last).total_seconds() / 3600.0)

    @staticmethod
    def _apply_decay(
        state: EmotionalState,
        baseline: dict[str, Any] | None,
        hours: float,
    ) -> None:
        base_feelings = _baseline_feelings(baseline)
        decayed: dict[str, float] = {}
        names = set(state.feelings or {}) | set(base_feelings)
        for name in names:
            cur = float((state.feelings or {}).get(name, 0.0))
            base = float(base_feelings.get(name, 0.0))
            val = decay_feeling(cur, base, hours, half_life_for(name))
            val = _clamp(val, 0, 1)
            if val >= FEELING_FLOOR or base > 0:
                decayed[name] = round(val, 4)
        state.feelings = decayed
        if baseline:
            bv = float(baseline.get("valence", 0.0))
            ba = float(baseline.get("arousal", 0.5))
            state.valence = _clamp(
                round(decay_feeling(state.valence, bv, hours, half_life_for("")), 4), -1, 1
            )
            state.arousal = _clamp(
                round(decay_feeling(state.arousal, ba, hours, half_life_for("")), 4), 0, 1
            )

    @staticmethod
    async def _get_or_create(
        session: AsyncSession, companion_id: uuid.UUID
    ) -> EmotionalState:
        state = await session.get(EmotionalState, companion_id)
        if state is None:
            state = EmotionalState(companion_id=companion_id)
            session.add(state)
            await session.flush()
        return state
