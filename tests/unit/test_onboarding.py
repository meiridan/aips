"""Wizard write path against a real schema (skipped when Postgres is absent)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from maya.companions import onboarding
from maya.companions.onboarding import AlreadyOnboarded, create_companion, get_state
from maya.companions.persona_spec import PersonaSpec
from maya.db.models import Companion, CompanionCommitment, Message
from tests.conftest import db_required

pytestmark = db_required


def _spec(**over):
    base = dict(
        name="מאיה",
        age=24,
        style="realistic",
        ethnicity="arab",
        hair_style="long",
        hair_color="blue",
        eye_color="hazel",
        body_type="curvy",
        breast_size="large",
        butt_size="large",
        personality="caregiver",
        relationship="girlfriend",
        occupation="nurse",
        clothing="cheerleader",
        voice_style="soft",
        hobbies=["yoga"],
    )
    base.update(over)
    return PersonaSpec(**base)


@pytest.fixture
def fake_genesis(monkeypatch):
    """Stub run_genesis — the real one costs an LLM call."""
    stub = AsyncMock(return_value=SimpleNamespace(first_message="היי, מה קורה?"))
    monkeypatch.setattr(onboarding, "run_genesis", stub)
    return stub


async def _count(sm, model, companion_id):
    async with sm() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(model.companion_id == companion_id)
        )


async def test_state_before_and_after(db_sessionmaker, seeded_ids, fake_genesis):
    _uid, cid = seeded_ids

    before = await get_state(db_sessionmaker, cid)
    assert before["onboarded"] is False
    assert before["spec"] is None

    await create_companion(db_sessionmaker, cid, _spec())

    after = await get_state(db_sessionmaker, cid)
    assert after["onboarded"] is True
    assert after["name"] == "מאיה"
    assert after["locale"] == "he"
    assert after["spec"]["ethnicity"] == "arab"


async def test_spec_rewrites_the_companion_row(db_sessionmaker, seeded_ids, fake_genesis):
    _uid, cid = seeded_ids
    first = await create_companion(db_sessionmaker, cid, _spec())
    assert first == "היי, מה קורה?"

    async with db_sessionmaker() as session:
        comp = await session.get(Companion, cid)
        assert comp.name == "מאיה"
        # caregiver maps onto the existing "devoted" template
        assert comp.template_id == "devoted"
        assert comp.onboarded_at is not None

    # genesis is the one that writes backstory/personality — it got the spec
    assert fake_genesis.await_args.kwargs["spec"].ethnicity == "arab"


async def test_second_submission_needs_reset(db_sessionmaker, seeded_ids, fake_genesis):
    _uid, cid = seeded_ids
    await create_companion(db_sessionmaker, cid, _spec())

    with pytest.raises(AlreadyOnboarded):
        await create_companion(db_sessionmaker, cid, _spec(name="נועה"))

    await create_companion(db_sessionmaker, cid, _spec(name="נועה"), reset=True)
    async with db_sessionmaker() as session:
        assert (await session.get(Companion, cid)).name == "נועה"


async def test_creation_clears_prior_history(db_sessionmaker, seeded_ids, fake_genesis):
    """A pre-wizard lazy companion may already hold an opener in the wrong voice."""
    uid, cid = seeded_ids
    async with db_sessionmaker() as session:
        session.add(Message(companion_id=cid, user_id=uid, role="assistant", content="Hi there!"))
        await session.commit()
    assert await _count(db_sessionmaker, Message, cid) == 1

    await create_companion(db_sessionmaker, cid, _spec())
    assert await _count(db_sessionmaker, Message, cid) == 0


async def test_cache_is_invalidated(db_sessionmaker, seeded_ids, fake_genesis):
    from maya import runtime_cache

    _uid, cid = seeded_ids
    runtime_cache.set_companion(cid, SimpleNamespace(name="stale"))
    await create_companion(db_sessionmaker, cid, _spec())
    assert runtime_cache.get_companion(cid) is None


async def test_reset_survives_a_commitment_pointing_at_a_message(
    db_sessionmaker, seeded_ids, fake_genesis
):
    """The 500 this reproduces: `companion_commitments.source_message_id` used to
    block the DELETE over `messages`, so re-creating her from the gallery or the
    wizard failed with a ForeignKeyViolationError."""
    uid, cid = seeded_ids
    async with db_sessionmaker() as session:
        message = Message(companion_id=cid, user_id=uid, role="user", content="אזכיר לך מחר")
        session.add(message)
        await session.flush()
        session.add(
            CompanionCommitment(
                companion_id=cid,
                content="לשאול איך עבר הראיון",
                commitment_type="follow_up",
                source_message_id=message.id,
            )
        )
        await session.commit()

    await create_companion(db_sessionmaker, cid, _spec(), reset=True)

    assert await _count(db_sessionmaker, Message, cid) == 0
    assert await _count(db_sessionmaker, CompanionCommitment, cid) == 0
