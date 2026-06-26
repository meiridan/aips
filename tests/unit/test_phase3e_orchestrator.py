"""Phase 3e — orchestrator integration test plan.

Full handle_message with a fake LLM + fake memory (no network), against the
real test DB. Verifies: reply returned, messages saved, post-processing applies
emotional/relationship/commitment updates, significant event logged, and the
debug step callback fires expected events.
"""

from __future__ import annotations

import pytest

_MOMENT_JSON = {
    "moment_type": "vulnerable_disclosure",
    "emotional_intensity": 0.9,  # > 0.8 → logs a significant event
    "emotional_delta": {
        "drop_feelings": [],
        "add_feelings": {"tender": 0.8},
        "valence_delta": 0.2,
        "arousal_delta": 0.1,
    },
    "character_priority": "presence_and_comfort",
    "detected_topics": ["family"],
    "sensitive_flags": [],
}
_COMMIT_JSON = {"commitments": [
    {"content": "I am a photographer", "commitment_type": "identity", "importance": 0.9},
]}


class _FakeLLM:
    def __init__(self):
        self.chat_calls = []
        self.json_calls = []

    async def chat(self, messages, **kwargs):
        self.chat_calls.append(messages)
        return "I'm right here with you."

    async def chat_json(self, messages, **kwargs):
        prompt = messages[0]["content"]
        self.json_calls.append(prompt)
        if "analyzing a moment" in prompt:
            return dict(_MOMENT_JSON)
        if "reveal about HERSELF" in prompt:
            return dict(_COMMIT_JSON)
        return {}


class _FakeMemory:
    def __init__(self):
        self.extracted = []

    async def search_relevant(self, *a, **k):
        return []

    async def extract_and_store(self, *, user_id, companion_id, user_message, assistant_message):
        self.extracted.append((user_message, assistant_message))
        return ["user shared something personal"]


def _make_orch(db_sessionmaker, llm, memory):
    from maya.companions.commitments import CommitmentService
    from maya.conversation.moment_analyzer import MomentAnalyzer
    from maya.conversation.orchestrator import Orchestrator
    from maya.emotional.service import EmotionalService
    from maya.relationship.service import RelationshipService

    return Orchestrator(
        llm=llm,
        memory=memory,
        sessionmaker=db_sessionmaker,
        emotional=EmotionalService(db_sessionmaker),
        relationship=RelationshipService(db_sessionmaker),
        commitments=CommitmentService(db_sessionmaker, llm=llm),
        moment_analyzer=MomentAnalyzer(llm),
    )


@pytest.mark.asyncio
async def test_handle_message_returns_reply(db_sessionmaker, seeded_ids):
    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    reply = await orch.handle_message(uid, cid, "my dad is in the hospital")
    assert reply == "I'm right here with you."


@pytest.mark.asyncio
async def test_handle_message_saves_both_messages(db_sessionmaker, seeded_ids):
    from sqlalchemy import select

    from maya.db.models import Message

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await orch.handle_message(uid, cid, "hey you")
    async with db_sessionmaker() as s:
        msgs = (await s.scalars(select(Message).where(Message.companion_id == cid))).all()
    roles = [m.role for m in msgs]
    assert "user" in roles and "assistant" in roles


@pytest.mark.asyncio
async def test_post_processing_updates_emotional_state(db_sessionmaker, seeded_ids):
    from maya.emotional.service import EmotionalService

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await orch.handle_message(uid, cid, "I need you")
    emo = await EmotionalService(db_sessionmaker).get(cid, baseline={"feelings": {}})
    assert "tender" in emo.feelings  # add_feelings from the moment delta


@pytest.mark.asyncio
async def test_post_processing_increments_interaction(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await orch.handle_message(uid, cid, "hi")
    rel = await RelationshipService(db_sessionmaker).get(cid, uid)
    assert rel.total_interactions == 1
    assert rel.last_interaction_at is not None


@pytest.mark.asyncio
async def test_post_processing_extracts_commitment(db_sessionmaker, seeded_ids):
    from maya.companions.commitments import CommitmentService

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await orch.handle_message(uid, cid, "tell me about you")
    commits = await CommitmentService(db_sessionmaker).get_recent(cid)
    assert any(c.content == "I am a photographer" for c in commits)


@pytest.mark.asyncio
async def test_high_intensity_logs_event(db_sessionmaker, seeded_ids):
    from sqlalchemy import select

    from maya.db.models import RelationshipEvent

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await orch.handle_message(uid, cid, "something heavy")
    async with db_sessionmaker() as s:
        events = (await s.scalars(
            select(RelationshipEvent).where(RelationshipEvent.companion_id == cid)
        )).all()
    assert any(e.event_type == "emotional_moment" for e in events)


@pytest.mark.asyncio
async def test_memory_extract_called(db_sessionmaker, seeded_ids):
    uid, cid = seeded_ids
    mem = _FakeMemory()
    orch = _make_orch(db_sessionmaker, _FakeLLM(), mem)
    await orch.handle_message(uid, cid, "remember this")
    assert mem.extracted  # extract_and_store ran in post-processing


@pytest.mark.asyncio
async def test_debug_callback_fires_events(db_sessionmaker, seeded_ids):
    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    events: list[tuple[str, str]] = []

    async def on_step(category, label, data):
        events.append((category, label))

    await orch.handle_message(uid, cid, "hi", on_step=on_step)
    cats = {c for c, _ in events}
    labels = " | ".join(lbl for _, lbl in events)
    assert {"step", "memory", "llm"} <= cats
    assert "Moment" in labels
    assert "complete" in labels.lower()


@pytest.mark.asyncio
async def test_stage_transition_after_five_turns(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    orch = _make_orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    for _ in range(5):
        await orch.handle_message(uid, cid, "hey")
    rel = await RelationshipService(db_sessionmaker).get(cid, uid)
    assert rel.total_interactions == 5
    assert rel.stage == "curious"  # strangers → curious at 5 interactions
