"""Multi-day conversation simulator (§P4.3).

Drives a `PersonaSimulator` against the real `Orchestrator` over a simulated
multi-day arc on an **isolated** user+companion, advancing simulated time
(emotional decay + day counter) at each day boundary and snapshotting state.

Cost is read back from the `llm_calls` table (every LLM call already logs
`cost_usd`) rather than threaded through the call stack.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from maya.companions.genesis import run_genesis
from maya.companions.templates import get_template
from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, LLMCall, User
from maya.db.session import get_sessionmaker
from maya.emotional.service import EmotionalService
from maya.llm.service import LLMService
from maya.relationship.service import RelationshipService
from tests.simulator.persona_chat import SKIP_TOKEN, PersonaSimulator
from tests.simulator.personas import PERSONAS

_TIME_OF_DAY = ["morning", "midday, on a break", "afternoon", "evening, after work", "late at night"]

# Each persona maps to a starting template so genesis produces a fitting Maya.
_PERSONA_TEMPLATE = {
    "lonely_dev": "devoted",
    "playful_artist": "flirt",
    "skeptical_tester": "best_friend",
    "needy_user": "devoted",
}


@dataclass
class SimulationResult:
    persona: str
    days: int
    seed: int
    transcript: list[dict]
    daily_snapshots: list[dict]
    final_state: dict
    all_memories: list[dict]
    relationship_events: list[dict]
    cost_usd: float
    # Ids of the isolated companion this run created (str for JSON). Let behavior
    # tests issue follow-up turns against the same Maya after the arc.
    user_id: str | None = None
    companion_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, default=str))

    @classmethod
    def from_dict(cls, data: dict) -> SimulationResult:
        return cls(**data)

    @classmethod
    def from_json(cls, path: str | Path) -> SimulationResult:
        return cls.from_dict(json.loads(Path(path).read_text()))


def pick_time_context(day: int, msg_idx: int) -> str:
    """A human-readable time label, e.g. 'Day 3, evening, after work'."""
    return f"Day {day}, {_TIME_OF_DAY[msg_idx % len(_TIME_OF_DAY)]}"


async def seed_fresh(persona_key: str, sessionmaker=None) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an ISOLATED user+companion (not the singleton) and run genesis."""
    sm = sessionmaker or get_sessionmaker()
    persona = PERSONAS[persona_key]
    template_id = _PERSONA_TEMPLATE.get(persona_key, "flirt")
    async with sm() as session:
        user = User(name=persona.name, description=persona.description)
        session.add(user)
        await session.flush()
        companion = Companion(user_id=user.id, name="Maya", template_id=template_id)
        session.add(companion)
        await session.commit()
        uid, cid = user.id, companion.id
    await run_genesis(cid, sessionmaker=sm)
    return uid, cid


async def snapshot_state(
    companion_id: uuid.UUID, user_id: uuid.UUID, template_id: str, sessionmaker=None
) -> dict:
    """Point-in-time state for daily snapshots + final_state."""
    sm = sessionmaker or get_sessionmaker()
    baseline = get_template(template_id).baseline_emotional
    emo = await EmotionalService(sm).get(companion_id, baseline=baseline)
    rel = await RelationshipService(sm).get(companion_id, user_id)
    return {
        "stage": rel.stage,
        "intimacy": rel.intimacy_level,
        "trust": rel.trust_level,
        "days_known": rel.days_known,
        "interactions": rel.total_interactions,
        "valence": emo.valence,
        "arousal": emo.arousal,
        "feelings": dict(emo.feelings),
    }


async def _sum_cost_since(start: datetime, sessionmaker) -> float:
    async with sessionmaker() as session:
        total = await session.scalar(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(
                LLMCall.timestamp >= start
            )
        )
    return float(total or 0)


async def simulate_relationship(
    persona_key: str,
    days: int = 30,
    messages_per_day_range: tuple[int, int] = (3, 10),
    seed: int = 42,
    sessionmaker=None,
    progress=None,  # optional callback(day, n_days)
) -> SimulationResult:
    """Run a multi-day simulated conversation; return state + transcript."""
    if persona_key not in PERSONAS:
        raise ValueError(f"Unknown persona: {persona_key!r}")
    sm = sessionmaker or get_sessionmaker()
    template_id = _PERSONA_TEMPLATE.get(persona_key, "flirt")
    started_at = datetime.now(UTC)

    uid, cid = await seed_fresh(persona_key, sessionmaker=sm)

    rng = random.Random(seed)
    llm = LLMService()
    persona_sim = PersonaSimulator(PERSONAS[persona_key], llm=llm)
    orch = Orchestrator(llm=llm, sessionmaker=sm)
    emotional = EmotionalService(sm)
    relationship = RelationshipService(sm)
    baseline = get_template(template_id).baseline_emotional

    transcript: list[dict] = []
    daily_snapshots: list[dict] = []

    for day in range(days):
        persona_sim.simulated_day = day
        if progress is not None:
            progress(day, days)

        # Skip ~15% of days entirely (realistic gaps).
        if rng.random() < 0.15:
            await emotional.decay(cid, hours_elapsed=24, baseline=baseline)
            await relationship.advance_days(cid, 1)
            daily_snapshots.append({"day": day, **await snapshot_state(cid, uid, template_id, sm)})
            continue

        n_messages = rng.randint(*messages_per_day_range)
        for msg_idx in range(n_messages):
            time_context = pick_time_context(day, msg_idx)
            last_maya = transcript[-1]["content"] if transcript else None
            user_message = await persona_sim.generate_next_message(last_maya, time_context)
            if user_message.strip() == SKIP_TOKEN or not user_message.strip():
                continue

            maya_response = await orch.handle_message(uid, cid, user_message)

            persona_sim.conversation_so_far.append({"role": "user", "content": user_message})
            persona_sim.conversation_so_far.append({"role": "assistant", "content": maya_response})
            transcript.append({"day": day, "time": time_context, "role": "user", "content": user_message})
            transcript.append({"day": day, "time": time_context, "role": "assistant", "content": maya_response})

        # Advance simulated time at day boundary.
        await emotional.decay(cid, hours_elapsed=24, baseline=baseline)
        await relationship.advance_days(cid, 1)
        daily_snapshots.append({"day": day, **await snapshot_state(cid, uid, template_id, sm)})

    from maya.memory.service import MemoryService

    all_memories = await MemoryService(sessionmaker=sm).get_all(uid, cid)
    events = await relationship.get_events(cid)
    cost = await _sum_cost_since(started_at, sm)

    return SimulationResult(
        persona=persona_key,
        days=days,
        seed=seed,
        transcript=transcript,
        daily_snapshots=daily_snapshots,
        final_state=await snapshot_state(cid, uid, template_id, sm),
        all_memories=all_memories,
        relationship_events=[
            {"event_type": e.event_type, "summary": e.summary,
             "occurred_at": e.occurred_at, "impact": e.impact}
            for e in events
        ],
        cost_usd=cost,
        user_id=str(uid),
        companion_id=str(cid),
    )
