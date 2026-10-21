"""/api/group and the /ws/group protocol, with the data layer mocked."""

from __future__ import annotations

import uuid
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import maya.web as web
from maya.auth.deps import current_user
from maya.companions.singleton import CompanionNotOnboarded
from maya.conversation.rooms import GroupRoom, Member
from maya.db.models import User

UID = uuid.uuid4()
ROOM = GroupRoom(
    conversation_id=uuid.uuid4(),
    user_id=UID,
    members=(
        Member(uuid.uuid4(), "primary", "מאיה"),
        Member(uuid.uuid4(), "lila", "לילה"),
    ),
)


@pytest.fixture
def client():
    web.app.dependency_overrides[current_user] = lambda: User(id=UID, name="Tester")
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.clear()


def test_api_group_lists_the_members(client, monkeypatch):
    monkeypatch.setattr(web, "resolve_group", AsyncMock(return_value=ROOM))
    body = client.get("/api/group").json()
    assert [m["slot"] for m in body["members"]] == ["primary", "lila"]
    assert body["conversation_id"] == str(ROOM.conversation_id)
    assert body["settings"] == {"response_length": 1, "talk_mode": "moderated"}


def test_api_group_before_her_companion_exists_is_409(client, monkeypatch):
    monkeypatch.setattr(web, "resolve_group", AsyncMock(side_effect=CompanionNotOnboarded("x")))
    res = client.get("/api/group")
    assert res.status_code == 409
    assert res.json()["detail"] == "companion_not_onboarded"


def test_catalog_reports_the_group_feature(client):
    assert client.get("/api/catalog").json()["features"]["group_chat"] is True


def test_group_socket_closes_4401_without_a_session(monkeypatch):
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=None))
    with TestClient(web.app) as c, c.websocket_connect("/ws/group") as ws:
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == web.WS_UNAUTHENTICATED


def test_group_socket_closes_4409_before_onboarding(monkeypatch):
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=UID))
    monkeypatch.setattr(web, "resolve_group", AsyncMock(side_effect=CompanionNotOnboarded("x")))
    with TestClient(web.app) as c, c.websocket_connect("/ws/group") as ws:
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == web.WS_COMPANION_NOT_ONBOARDED


class _FakeGroup:
    def __init__(self):
        self.calls: list[tuple] = []
        self.settings: list = []

    async def run_turn(self, room, content, *, target, emit, cancel, settings, on_step):
        self.calls.append((content, target))
        self.settings.append(settings.as_dict())
        await emit({"type": "turn_start", "addressed": ["lila"]})
        await emit({"type": "message_start", "speaker": "lila"})
        await emit({"type": "message_chunk", "speaker": "lila", "content": "היי"})
        await emit({"type": "message_end", "speaker": "lila"})
        await emit({"type": "turn_end"})
        return []


def test_group_socket_protocol(monkeypatch):
    fake = _FakeGroup()
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=UID))
    monkeypatch.setattr(web, "resolve_group", AsyncMock(return_value=ROOM))
    monkeypatch.setattr(web, "load_transcript", AsyncMock(return_value=[]))
    monkeypatch.setattr(web.entitlements, "quota_exceeded", AsyncMock(return_value=False))
    monkeypatch.setattr(web, "get_group_orchestrator", lambda: fake)

    with TestClient(web.app) as c, c.websocket_connect("/ws/group") as ws:
        members = ws.receive_json()
        assert members["type"] == "members"
        assert [m["name"] for m in members["members"]] == ["מאיה", "לילה"]
        assert ws.receive_json() == {
            "type": "settings",
            "response_length": 1,
            "talk_mode": "moderated",
        }
        assert ws.receive_json() == {"type": "history_end"}

        ws.send_json({"content": "  לילה, היי ", "target": "lila"})
        seen = []
        while True:
            event = ws.receive_json()
            if event["type"] == "debug":
                continue
            seen.append(event)
            if event["type"] == "turn_end":
                break

    assert seen[0] == {"type": "message", "role": "user", "content": "לילה, היי"}
    assert [e["type"] for e in seen[1:]] == [
        "turn_start",
        "message_start",
        "message_chunk",
        "message_end",
        "turn_end",
    ]
    assert fake.calls == [("לילה, היי", "lila")]


def test_group_socket_saves_settings_without_starting_a_turn(monkeypatch):
    fake = _FakeGroup()
    save = AsyncMock()
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=UID))
    monkeypatch.setattr(web, "resolve_group", AsyncMock(return_value=ROOM))
    monkeypatch.setattr(web, "load_transcript", AsyncMock(return_value=[]))
    monkeypatch.setattr(web, "save_settings", save)
    monkeypatch.setattr(web.entitlements, "quota_exceeded", AsyncMock(return_value=False))
    monkeypatch.setattr(web, "get_group_orchestrator", lambda: fake)

    with TestClient(web.app) as c, c.websocket_connect("/ws/group") as ws:
        for _ in range(3):  # members, settings, history_end
            ws.receive_json()
        ws.send_json({"type": "settings", "talk_mode": "free", "response_length": 2})
        assert ws.receive_json() == {"type": "settings", "response_length": 2, "talk_mode": "free"}
        assert fake.calls == []

        ws.send_json({"content": "היי"})
        while ws.receive_json()["type"] != "turn_end":
            pass

    save.assert_awaited_once_with(
        ANY, ROOM.conversation_id, {"response_length": 2, "talk_mode": "free"}
    )
    assert fake.calls == [("היי", None)]
    assert fake.settings == [{"response_length": 2, "talk_mode": "free"}]


def test_group_socket_honours_the_quota(monkeypatch):
    fake = _FakeGroup()
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=UID))
    monkeypatch.setattr(web, "resolve_group", AsyncMock(return_value=ROOM))
    monkeypatch.setattr(web, "load_transcript", AsyncMock(return_value=[]))
    monkeypatch.setattr(web.entitlements, "quota_exceeded", AsyncMock(return_value=True))
    monkeypatch.setattr(web, "get_group_orchestrator", lambda: fake)

    with TestClient(web.app) as c, c.websocket_connect("/ws/group") as ws:
        for _ in range(3):  # members, settings, history_end
            ws.receive_json()
        ws.send_json({"content": "היי"})
        assert ws.receive_json() == {"type": "quota_exceeded"}
    assert fake.calls == []
