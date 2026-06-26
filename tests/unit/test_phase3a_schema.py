"""Phase 3a — schema & state models test plan.

Pure-logic: template load + model shape.
DB-backed (skipped if no Postgres): migration up/down clean + model round-trip.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

# ───────────────────────── templates (P3.2) ─────────────────────────


@pytest.mark.parametrize("tid", ["flirt", "devoted", "best_friend"])
def test_template_loads(tid):
    from maya.companions.templates import TEMPLATES

    t = TEMPLATES[tid]
    assert t.id == tid
    assert t.name and t.description and t.baseline_tone
    assert isinstance(t.traits, list) and len(t.traits) >= 1
    assert "feelings" in t.baseline_emotional


def test_template_count():
    from maya.companions.templates import TEMPLATES

    assert len(TEMPLATES) == 3


@pytest.mark.parametrize("tid,unknown", [("flirt", "flirt"), ("nope", "flirt"), ("", "flirt")])
def test_get_template_defaults_to_flirt(tid, unknown):
    from maya.companions.templates import get_template

    assert get_template(tid).id == unknown


def test_flirt_baseline_values():
    from maya.companions.templates import TEMPLATES

    be = TEMPLATES["flirt"].baseline_emotional
    assert be["valence"] == 0.5 and be["arousal"] == 0.6
    assert be["feelings"]["playful"] == 0.6


# ───────────────────────── model shape (P3.1) ─────────────────────────


@pytest.mark.parametrize("model,table", [
    ("EmotionalState", "emotional_state"),
    ("RelationshipState", "relationship_state"),
    ("RelationshipEvent", "relationship_events"),
    ("CompanionCommitment", "companion_commitments"),
])
def test_phase3_tablenames(model, table):
    import maya.db.models as m

    assert getattr(m, model).__tablename__ == table


@pytest.mark.parametrize("col", ["companion_id", "valence", "arousal", "dominance", "feelings", "last_updated"])
def test_emotional_columns(col):
    from maya.db.models import EmotionalState

    assert col in EmotionalState.__table__.columns.keys()


@pytest.mark.parametrize("col", [
    "id", "companion_id", "user_id", "stage", "intimacy_level",
    "trust_level", "days_known", "total_interactions", "last_interaction_at", "created_at",
])
def test_relationship_columns(col):
    from maya.db.models import RelationshipState

    assert col in RelationshipState.__table__.columns.keys()


@pytest.mark.parametrize("col", ["id", "companion_id", "event_type", "summary", "impact", "occurred_at"])
def test_event_columns(col):
    from maya.db.models import RelationshipEvent

    assert col in RelationshipEvent.__table__.columns.keys()


@pytest.mark.parametrize("col", [
    "id", "companion_id", "content", "commitment_type", "status",
    "importance", "source_message_id", "created_at",
])
def test_commitment_columns(col):
    from maya.db.models import CompanionCommitment

    assert col in CompanionCommitment.__table__.columns.keys()


@pytest.mark.parametrize("col", ["personality", "backstory"])
def test_companion_phase3_columns(col):
    from maya.db.models import Companion

    assert col in Companion.__table__.columns.keys()


# ───────────────────────── DB round-trip (P3.1) ─────────────────────────


@pytest.mark.asyncio
async def test_emotional_state_round_trip(db_sessionmaker, seeded_ids):
    from maya.db.models import EmotionalState

    _uid, cid = seeded_ids
    async with db_sessionmaker() as s:
        s.add(EmotionalState(companion_id=cid, valence=0.3, arousal=0.7,
                             feelings={"playful": 0.6}))
        await s.commit()
    async with db_sessionmaker() as s:
        got = await s.get(EmotionalState, cid)
        assert got is not None
        assert got.valence == 0.3 and got.arousal == 0.7
        assert got.feelings == {"playful": 0.6}
        assert got.dominance == 0.5  # server default


@pytest.mark.asyncio
async def test_relationship_state_round_trip(db_sessionmaker, seeded_ids):
    from maya.db.models import RelationshipState

    uid, cid = seeded_ids
    async with db_sessionmaker() as s:
        s.add(RelationshipState(companion_id=cid, user_id=uid))
        await s.commit()
    async with db_sessionmaker() as s:
        from sqlalchemy import select

        rs = (await s.scalars(select(RelationshipState).where(
            RelationshipState.companion_id == cid))).one()
        assert rs.stage == "strangers"
        assert rs.intimacy_level == 1 and rs.trust_level == 1
        assert rs.total_interactions == 0


@pytest.mark.asyncio
async def test_commitment_and_event_round_trip(db_sessionmaker, seeded_ids):
    from sqlalchemy import select

    from maya.db.models import CompanionCommitment, RelationshipEvent

    _uid, cid = seeded_ids
    async with db_sessionmaker() as s:
        s.add(CompanionCommitment(companion_id=cid, content="I am a photographer",
                                  commitment_type="identity", importance=0.9))
        s.add(RelationshipEvent(companion_id=cid, event_type="stage_transition",
                                summary="to flirting", impact={"intimacy_delta": 1}))
        await s.commit()
    async with db_sessionmaker() as s:
        c = (await s.scalars(select(CompanionCommitment))).one()
        assert c.content == "I am a photographer" and c.status == "active"
        e = (await s.scalars(select(RelationshipEvent))).one()
        assert e.impact == {"intimacy_delta": 1}


@pytest.mark.asyncio
async def test_companion_personality_backstory_round_trip(db_sessionmaker, seeded_ids):
    from maya.db.models import Companion

    _uid, cid = seeded_ids
    async with db_sessionmaker() as s:
        comp = await s.get(Companion, cid)
        comp.personality = {"traits": ["witty"]}
        comp.backstory = "Grew up in Haifa."
        await s.commit()
    async with db_sessionmaker() as s:
        comp = await s.get(Companion, cid)
        assert comp.personality == {"traits": ["witty"]}
        assert comp.backstory == "Grew up in Haifa."


# ───────────────────────── migration up/down (P3.1) ─────────────────────────


@pytest.mark.asyncio
async def test_migration_round_trips_via_metadata(db_sessionmaker):
    """Schema builds (create_all) and tears down (drop_all) cleanly.

    db_sessionmaker drops+creates all tables around the test; reaching here
    with a usable connection proves the Phase-3 DDL is self-consistent.
    """
    async with db_sessionmaker() as s:
        for tbl in ("emotional_state", "relationship_state",
                    "relationship_events", "companion_commitments"):
            n = await s.scalar(text(f"SELECT count(*) FROM {tbl}"))
            assert n == 0
