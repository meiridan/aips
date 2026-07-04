"""Web POST /companion/response_length endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import maya.web as web


def _client():
    return TestClient(web.app)


def test_post_sets_level(monkeypatch):
    uid, cid = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(web, "resolve_singleton", AsyncMock(return_value=(uid, cid, False, None)))
    set_len = AsyncMock(return_value=3)
    monkeypatch.setattr(web, "set_response_length", set_len)

    resp = _client().post("/companion/response_length", json={"level": 3})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "level": 3}
    set_len.assert_awaited_once()
    assert set_len.await_args.args[2] == 3  # (sm, cid, level)


def test_post_rejects_bad_level(monkeypatch):
    # parse fails before any DB access → 422, no resolve/set needed.
    resp = _client().post("/companion/response_length", json={"level": 9})
    assert resp.status_code == 422
