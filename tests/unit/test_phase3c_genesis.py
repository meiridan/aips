"""Phase 3c — genesis test plan.

structure: generate_genesis returns a valid GenesisResult (mocked LLM).
end-to-end (DB): run_genesis writes backstory, feelings, relationship,
commitments, and the opening assistant message.
"""

from __future__ import annotations

import pytest

_GENESIS_JSON = {
    "backstory": "I grew up in Haifa, became a photographer, and I bite my nails when nervous.",
    "initial_feelings": {"valence": 0.4, "arousal": 0.6, "feelings": {"curious": 0.7}},
    "seed_commitments": [
        {"content": "I am a photographer", "commitment_type": "identity", "importance": 0.9},
        {"content": "I love the sea", "commitment_type": "preference", "importance": 0.6},
    ],
    "first_message": "hey — saw you lurking. what's got your attention today?",
}


class _FakeLLM:
    def __init__(self, payload=None):
        self.payload = payload or _GENESIS_JSON
        self.calls = []

    async def chat_json(self, messages, schema=None, **kwargs):
        self.calls.append({"messages": messages, "schema": schema, "kwargs": kwargs})
        return dict(self.payload)


# ───────────────────────── structure (mock LLM, no DB) ─────────────────────


@pytest.mark.asyncio
async def test_generate_genesis_structure():
    from types import SimpleNamespace

    from maya.companions.genesis import GenesisResult, generate_genesis

    companion = SimpleNamespace(name="Maya", template_id="flirt")
    user = SimpleNamespace(name="Idan", description="curious engineer")
    llm = _FakeLLM()
    res = await generate_genesis(companion, user, llm)
    assert isinstance(res, GenesisResult)
    assert res.backstory and res.first_message
    assert res.initial_feelings["feelings"]["curious"] == 0.7
    assert len(res.seed_commitments) == 2


@pytest.mark.asyncio
async def test_generate_genesis_uses_main_tier_and_template():
    from types import SimpleNamespace

    from maya.companions.genesis import generate_genesis

    companion = SimpleNamespace(name="Maya", template_id="devoted")
    user = SimpleNamespace(name="Idan", description=None)
    llm = _FakeLLM()
    await generate_genesis(companion, user, llm)
    call = llm.calls[0]
    assert call["kwargs"]["model_tier"] == "main"
    # devoted template description should be in the rendered prompt
    assert "Loyal, attentive" in call["messages"][0]["content"]
    # None description falls back to the default intent line
    assert "open to whatever connection forms" in call["messages"][0]["content"]


# ───────────────────────── end-to-end (DB + mock LLM) ─────────────────────


@pytest.mark.asyncio
async def test_run_genesis_end_to_end(db_sessionmaker, seeded_ids):
    from sqlalchemy import select

    from maya.companions.commitments import CommitmentService
    from maya.companions.genesis import run_genesis
    from maya.db.models import Companion, Message
    from maya.emotional.service import EmotionalService
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    llm = _FakeLLM()
    result = await run_genesis(cid, sessionmaker=db_sessionmaker, llm=llm)
    assert result.first_message

    async with db_sessionmaker() as s:
        comp = await s.get(Companion, cid)
        assert "Haifa" in comp.backstory
        assert comp.personality["template_id"] == "flirt"
        msgs = (await s.scalars(select(Message).where(Message.companion_id == cid))).all()
        assert any(m.role == "assistant" and "lurking" in m.content for m in msgs)

    emo = await EmotionalService(db_sessionmaker).get(
        cid, baseline={"feelings": {"playful": 0.6}}
    )
    assert "curious" in emo.feelings or "playful" in emo.feelings

    rel = await RelationshipService(db_sessionmaker).get(cid, uid)
    assert rel.stage == "strangers"

    commits = await CommitmentService(db_sessionmaker).get_recent(cid)
    contents = {c.content for c in commits}
    assert "I am a photographer" in contents
    assert len(commits) == 2


@pytest.mark.asyncio
async def test_run_genesis_missing_companion_raises(db_sessionmaker):
    import uuid

    from maya.companions.genesis import run_genesis

    with pytest.raises(ValueError):
        await run_genesis(uuid.uuid4(), sessionmaker=db_sessionmaker, llm=_FakeLLM())
