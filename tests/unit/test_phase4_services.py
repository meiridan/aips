"""Phase 4 — reusable service additions the simulator depends on.

`advance_days` (simulated-time day counter) and `get_events` (relationship-event
fetch) back the multi-day runner + snapshot/eval-sample building.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_advance_days_bumps_days_known(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    await svc.initialize(cid, uid)

    await svc.advance_days(cid)  # default n=1
    rel = await svc.get(cid, uid)
    assert rel.days_known == 1

    await svc.advance_days(cid, n=4)
    rel = await svc.get(cid, uid)
    assert rel.days_known == 5


@pytest.mark.asyncio
async def test_advance_days_noop_without_state(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    _uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    # No relationship row yet → must not raise.
    await svc.advance_days(cid)


@pytest.mark.asyncio
async def test_get_events_returns_newest_first(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    await svc.initialize(cid, uid)
    await svc.log_event(cid, "first", "earliest")
    await svc.log_event(cid, "second", "latest")

    events = await svc.get_events(cid)
    assert [e.event_type for e in events] == ["second", "first"]


@pytest.mark.asyncio
async def test_get_events_respects_limit(db_sessionmaker, seeded_ids):
    from maya.relationship.service import RelationshipService

    uid, cid = seeded_ids
    svc = RelationshipService(db_sessionmaker)
    await svc.initialize(cid, uid)
    for i in range(5):
        await svc.log_event(cid, f"e{i}", "x")

    events = await svc.get_events(cid, limit=2)
    assert len(events) == 2
