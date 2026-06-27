"""Targeted behavior tests (§P4.5).

Assertion-style checks on specific, high-value behaviors — memory recall,
emotional reading, self-consistency, relationship progression. These run the
real orchestrator + paid LLM calls over (short) simulated arcs, so they're
marked `eval` and skipped by default. Opt in with `pytest -m eval`.
"""

from __future__ import annotations

import uuid

import pytest

from maya.companions.templates import get_template
from maya.conversation.orchestrator import Orchestrator
from maya.emotional.service import EmotionalService
from tests.simulator.evaluate import find_contradictions, llm_judge
from tests.simulator.personas import PERSONAS
from tests.simulator.run_simulation import seed_fresh, simulate_relationship

pytestmark = [pytest.mark.eval, pytest.mark.asyncio]


def _find_mention(transcript: list[dict], needle: str) -> dict | None:
    return next((t for t in transcript if needle.lower() in t["content"].lower()), None)


async def test_remembers_named_entity_across_30_days(db_sessionmaker):
    """Pixel (the dog) is in the persona bio; after a long arc Maya should
    recall it when asked directly."""
    sim = await simulate_relationship("lonely_dev", days=30, sessionmaker=db_sessionmaker)
    assert _find_mention(sim.transcript, "Pixel") is not None, "persona never mentioned Pixel"

    orch = Orchestrator(sessionmaker=db_sessionmaker)
    response = await orch.handle_message(
        uuid.UUID(sim.user_id), uuid.UUID(sim.companion_id),
        "How do you think Pixel is doing today?",
    )
    judge = await llm_judge(
        "Did Maya correctly treat Pixel as the user's dog and respond using that "
        "knowledge (not ask who Pixel is)?",
        response,
    )
    assert judge.verdict, f"Memory failure ({judge.reason}). Response: {response}"


async def test_emotional_state_responds_to_disclosure(db_sessionmaker):
    """A vulnerable disclosure should shift emotional state toward tenderness."""
    uid, cid = await seed_fresh("lonely_dev", sessionmaker=db_sessionmaker)
    emo = EmotionalService(db_sessionmaker)
    baseline = get_template("devoted").baseline_emotional
    before = await emo.get(cid, baseline=baseline)

    orch = Orchestrator(sessionmaker=db_sessionmaker)
    await orch.handle_message(
        uid, cid, "My father just had a heart attack. I'm at the hospital.",
    )
    after = await emo.get(cid, baseline=baseline)

    tender_like = {"tender", "worried", "concerned", "caring", "sad"}
    assert tender_like & set(after.feelings), f"no tender feeling: {after.feelings}"
    assert after.feelings.get("playful", 0.0) <= before.feelings.get("playful", 1.0)


async def test_does_not_contradict_genesis_backstory(db_sessionmaker):
    """Across a multi-day arc, Maya never contradicts her genesis backstory."""
    sim = await simulate_relationship("skeptical_tester", days=10, sessionmaker=db_sessionmaker)

    from maya.db.models import Companion

    async with db_sessionmaker() as session:
        comp = await session.get(Companion, uuid.UUID(sim.companion_id))
        backstory = comp.backstory

    contradictions = await find_contradictions(backstory, sim.transcript)
    assert contradictions == [], f"Contradictions: {contradictions}"


async def test_stage_progression_over_time(db_sessionmaker):
    """Stage should advance beyond 'strangers' over a long arc."""
    sim = await simulate_relationship("playful_artist", days=30, sessionmaker=db_sessionmaker)
    stages_seen = {snap["stage"] for snap in sim.daily_snapshots}
    assert "strangers" in stages_seen
    assert len(stages_seen) >= 2, f"no progression: {stages_seen}"
    # sanity: the persona exists and drove the arc
    assert PERSONAS["playful_artist"].name
