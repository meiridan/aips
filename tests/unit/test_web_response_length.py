"""Web POST /companion/response_length endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import maya.web as web
from maya.auth.deps import current_user
from maya.db.models import User

UID, CID = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def _client(monkeypatch):
    monkeypatch.setattr(web, "resolve_for_user", AsyncMock(return_value=CID))
    web.app.dependency_overrides[current_user] = lambda: User(id=UID, name="Tester")
    try:
        yield lambda: TestClient(web.app)
    finally:
        web.app.dependency_overrides.clear()


def test_post_sets_level(monkeypatch, _client):
    set_len = AsyncMock(return_value=3)
    monkeypatch.setattr(web, "set_response_length", set_len)

    resp = _client().post("/companion/response_length", json={"level": 3})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "level": 3}
    set_len.assert_awaited_once()
    sm, companion_id, level = set_len.await_args.args
    assert (companion_id, level) == (CID, 3)


def test_post_rejects_bad_level(monkeypatch, _client):
    # parse fails before any DB access → 422, no resolve/set needed.
    resp = _client().post("/companion/response_length", json={"level": 9})
    assert resp.status_code == 422
