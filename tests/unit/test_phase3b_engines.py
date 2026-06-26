"""Phase 3b — emotional + relationship engines + commitments test plan.

Pure-logic: decay math, every stage transition predicate.
DB-backed (skipped if no Postgres): emotional service, relationship service,
commitment CRUD.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# ───────────────────────── decay math (P3.4, pure) ─────────────────────────


def test_decay_half_after_one_half_life():
    from maya.emotional.constants import decay_feeling

    assert decay_feeling(1.0, 0.0, 12.0, 12.0) == pytest.approx(0.5)


def test_decay_quarter_after_two_half_lives():
    from maya.emotional.constants import decay_feeling

    assert decay_feeling(1.0, 0.0, 24.0, 12.0) == pytest.approx(0.25)


def test_decay_zero_elapsed_unchanged():
    from maya.emotional.constants import decay_feeling

    assert decay_feeling(0.8, 0.2, 0.0, 6.0) == pytest.approx(0.8)


def test_decay_toward_nonzero_baseline():
    from maya.emotional.constants import decay_feeling

    # gap 0.4 → 0.2 after one half-life → 0.6 + 0.2 = 0.8
    assert decay_feeling(1.0, 0.6, 12.0, 12.0) == pytest.approx(0.8)


def test_decay_different_rates():
    from maya.emotional.constants import decay_feeling, half_life_for

    playful = decay_feeling(1.0, 0.0, 4.0, half_life_for("playful"))   # hl 2
    in_love = decay_feeling(1.0, 0.0, 4.0, half_life_for("in_love"))   # hl 168
    assert playful < in_love  # fast feeling decays more


def test_half_life_default_for_unknown():
    from maya.emotional.constants import DEFAULT_HALF_LIFE, half_life_for

    assert half_life_for("nonexistent_feeling") == DEFAULT_HALF_LIFE


def test_decay_nonpositive_half_life_returns_baseline():
    from maya.emotional.constants import decay_feeling

    assert decay_feeling(1.0, 0.3, 5.0, 0.0) == 0.3


# ───────────────────────── stage transitions (P3.5, pure) ─────────────────

from maya.relationship import transitions as T  # noqa: E402
from maya.relationship.transitions import (  # noqa: E402
    Stage,
    TransitionContext,
    next_stage,
)


def _ctx(stage, **kw):
    base = dict(total_interactions=0, intimacy_level=1, trust_level=1, days_known=0)
    base.update(kw)
    return TransitionContext(stage=stage.value if isinstance(stage, Stage) else stage, **base)


def _evt(t, days_ago=0):
    return T.EventLike(t, datetime.now(UTC) - timedelta(days=days_ago))


def test_strangers_to_curious():
    assert next_stage(_ctx(Stage.STRANGERS, total_interactions=5)) == Stage.CURIOUS
    assert next_stage(_ctx(Stage.STRANGERS, total_interactions=4)) is None


def test_curious_to_flirting():
    assert next_stage(_ctx(Stage.CURIOUS, total_interactions=20, intimacy_level=3)) == Stage.FLIRTING
    assert next_stage(_ctx(Stage.CURIOUS, total_interactions=20, intimacy_level=2)) is None
    assert next_stage(_ctx(Stage.CURIOUS, total_interactions=19, intimacy_level=5)) is None


def test_flirting_to_dating_via_intimacy():
    assert next_stage(_ctx(Stage.FLIRTING, intimacy_level=5)) == Stage.DATING


def test_flirting_to_dating_via_event():
    c = _ctx(Stage.FLIRTING, intimacy_level=1)
    c.events = [_evt("intimacy_breakthrough")]
    assert next_stage(c) == Stage.DATING


def test_dating_to_in_love_via_event():
    c = _ctx(Stage.DATING, intimacy_level=1, days_known=1)
    c.events = [_evt("first_i_love_you")]
    assert next_stage(c) == Stage.IN_LOVE


def test_dating_to_in_love_via_time_and_intimacy():
    assert next_stage(_ctx(Stage.DATING, days_known=14, intimacy_level=7)) == Stage.IN_LOVE
    assert next_stage(_ctx(Stage.DATING, days_known=14, intimacy_level=6)) is None


def test_in_love_to_committed():
    assert next_stage(_ctx(Stage.IN_LOVE, days_known=30, trust_level=7)) == Stage.COMMITTED


def test_in_love_to_conflict_on_recent_argument():
    c = _ctx(Stage.IN_LOVE, days_known=5)
    c.events = [_evt("argument", days_ago=1)]
    assert next_stage(c) == Stage.CONFLICT


def test_committed_to_deepening():
    assert next_stage(_ctx(Stage.COMMITTED, days_known=60, trust_level=9)) == Stage.DEEPENING


def test_conflict_to_reconciled():
    c = _ctx(Stage.CONFLICT)
    c.events = [_evt("argument", days_ago=3), _evt("reconciliation", days_ago=1)]
    assert next_stage(c) == Stage.RECONCILED


def test_conflict_to_drifted_after_silence():
    c = _ctx(Stage.CONFLICT, last_interaction_at=datetime.now(UTC) - timedelta(days=8))
    assert next_stage(c) == Stage.DRIFTED


def test_reconciled_to_in_love_after_quiet_week():
    c = _ctx(Stage.RECONCILED)
    c.events = [_evt("argument", days_ago=10)]
    assert next_stage(c) == Stage.IN_LOVE


def test_universal_drift_from_any_stage():
    c = _ctx(Stage.FLIRTING, intimacy_level=9,
             last_interaction_at=datetime.now(UTC) - timedelta(days=15))
    assert next_stage(c) == Stage.DRIFTED  # drift wins over flirting→dating


def test_no_transition_when_nothing_qualifies():
    assert next_stage(_ctx(Stage.STRANGERS, total_interactions=1)) is None


def test_unknown_stage_returns_none():
    assert next_stage(_ctx("nonsense", total_interactions=99)) is None


# predicate units
def test_has_event_after_event():
    s = _ctx(Stage.CONFLICT)
    s.events = [_evt("argument", days_ago=5), _evt("reconciliation", days_ago=1)]
    assert T.has_event_after_event(s, "reconciliation", "argument") is True
    assert T.has_event_after_event(s, "argument", "reconciliation") is False


def test_days_since_last_infinite_when_never():
    assert T.days_since_last(_ctx(Stage.STRANGERS)) == float("inf")


# ───────────────────────── emotional service (DB) ─────────────────────────


@pytest.mark.asyncio
async def test_emotional_set_initial_and_get(db_sessionmaker, seeded_ids):
    from maya.emotional.service import EmotionalService

    _uid, cid = seeded_ids
    svc = EmotionalService(db_sessionmaker)
    await svc.set_initial(cid, {"valence": 0.4, "arousal": 0.7, "feelings": {"playful": 0.9}})
    state = await svc.get(cid, baseline={"valence": 0.4, "arousal": 0.7, "feelings": {"playful": 0.6}})
    assert state.valence == pytest.approx(0.4, abs=0.01)
    assert "playful" in state.feelings


@pytest.mark.asyncio
async def test_emotional_decay_reduces_feeling(db_sessionmaker, seeded_ids):
    from maya.emotional.service import EmotionalService

    _uid, cid = seeded_ids
    svc = EmotionalService(db_sessionmaker)
    await svc.set_initial(cid, {"valence": 0.0, "arousal": 0.5, "feelings": {"excited": 1.0}})
    # excited half-life 4h → after 4h ≈ 0.5 toward baseline 0
    state = await svc.decay(cid, hours_elapsed=4.0, baseline={"feelings": {}})
    assert state.feelings["excited"] == pytest.approx(0.5, abs=0.02)


@pytest.mark.asyncio
async def test_emotional_update_after_message(db_sessionmaker, seeded_ids):
    from maya.emotional.service import EmotionalDelta, EmotionalService

    _uid, cid = seeded_ids
    svc = EmotionalService(db_sessionmaker)
    await svc.set_initial(cid, {"valence": 0.0, "arousal": 0.5, "feelings": {"calm": 0.5}})
    delta = EmotionalDelta(drop_feelings=["calm"], add_feelings={"happy_to_see_him": 0.8},
                           valence_delta=0.3, arousal_delta=0.2)
    state = await svc.update_after_message(cid, delta)
    assert "calm" not in state.feelings
    assert state.feelings["happy_to_see_him"] == pytest.approx(0.8)
    assert state.valence == pytest.approx(0.3) and state.arousal == pytest.approx(0.7)


# ───────────────────────── relationship service (DB) ─────────────────────


@pytest.mark.asyncio
async def test_relationship_initialize_and_increment(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    rel = await svc.initialize(cid, uid)
    assert rel.stage == "strangers" and rel.total_interactions == 0
    for _ in range(3):
        await svc.increment_interaction(cid)
    rel = await svc.get(cid, uid)
    assert rel.total_interactions == 3
    assert rel.last_interaction_at is not None


@pytest.mark.asyncio
async def test_relationship_log_event_applies_impact(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    await svc.initialize(cid, uid)
    await svc.log_event(cid, "emotional_moment", "Intense", impact={"intimacy_delta": 2, "trust_delta": 1})
    rel = await svc.get(cid, uid)
    assert rel.intimacy_level == 3 and rel.trust_level == 2


@pytest.mark.asyncio
async def test_relationship_stage_transition_live(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService
    from maya.relationship.transitions import Stage

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    await svc.initialize(cid, uid)
    for _ in range(5):
        await svc.increment_interaction(cid)
    new = await svc.evaluate_stage_transition(cid)
    assert new == Stage.CURIOUS
    rel = await svc.get(cid, uid)
    assert rel.stage == "curious"
    # second eval: no further transition yet
    assert await svc.evaluate_stage_transition(cid) is None


# ───────────────────────── commitments CRUD (DB) ─────────────────────────


@pytest.mark.asyncio
async def test_commitment_add_and_get_recent_ordered(db_sessionmaker, seeded_ids):
    from maya.companions.commitments import CommitmentService

    _uid, cid = seeded_ids
    svc = CommitmentService(db_sessionmaker)
    await svc.add(cid, "I like wine", "preference", importance=0.4)
    await svc.add(cid, "I am a photographer", "identity", importance=0.9)
    await svc.add(cid, "Honesty matters", "opinion", importance=0.6)
    rows = await svc.get_recent(cid, limit=10)
    assert len(rows) == 3
    assert [r.importance for r in rows] == [0.9, 0.6, 0.4]  # importance desc
    assert rows[0].content == "I am a photographer"


@pytest.mark.asyncio
async def test_commitment_limit_respected(db_sessionmaker, seeded_ids):
    from maya.companions.commitments import CommitmentService

    _uid, cid = seeded_ids
    svc = CommitmentService(db_sessionmaker)
    for i in range(5):
        await svc.add(cid, f"fact {i}", "identity", importance=0.5)
    rows = await svc.get_recent(cid, limit=2)
    assert len(rows) == 2
