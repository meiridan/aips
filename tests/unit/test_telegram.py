"""Telegram channel: client chunking, update routing, and the webhook route."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from maya.telegram import client as client_mod
from maya.telegram import service as service_mod
from maya.telegram.client import MAX_MESSAGE_LEN, TelegramClient, _chunk
from maya.telegram.service import TelegramService


# ─────────────────────────── client: chunking ───────────────────────────


def test_chunk_short_text_single_piece():
    assert _chunk("hello") == ["hello"]


def test_chunk_empty_is_placeholder():
    assert _chunk("") == ["..."]


def test_chunk_long_text_respects_limit():
    text = "x" * (MAX_MESSAGE_LEN * 2 + 50)
    pieces = _chunk(text)
    assert len(pieces) >= 3
    assert all(len(p) <= MAX_MESSAGE_LEN for p in pieces)
    assert "".join(pieces) == text


class _FakeResponse:
    def __init__(self) -> None:
        self.status_code = 200
        self.text = "{}"


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in capturing posts."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        _FakeAsyncClient.calls.append({"url": url, "json": json})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_send_message_posts_to_bot_api(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", _FakeAsyncClient)
    tc = TelegramClient("TOKEN123")
    await tc.send_message(42, "hi there")
    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"].endswith("/botTOKEN123/sendMessage")
    assert call["json"] == {"chat_id": 42, "text": "hi there"}


@pytest.mark.asyncio
async def test_send_message_splits_long_text(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", _FakeAsyncClient)
    tc = TelegramClient("T")
    await tc.send_message(1, "y" * (MAX_MESSAGE_LEN + 10))
    assert len(_FakeAsyncClient.calls) == 2


# ─────────────────────────── service: routing ───────────────────────────


def _make_service():
    svc = TelegramService.__new__(TelegramService)
    svc.client = AsyncMock()
    svc.orchestrator = AsyncMock()
    svc._sessionmaker = None
    return svc


@pytest.mark.asyncio
async def test_handle_update_ignores_non_message():
    svc = _make_service()
    await svc.handle_update({"edited_message": {"text": "hi"}})
    svc.orchestrator.handle_message.assert_not_called()
    svc.client.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_ignores_non_text():
    svc = _make_service()
    await svc.handle_update({"message": {"chat": {"id": 5}, "sticker": {}}})
    svc.orchestrator.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_routes_text_to_orchestrator():
    svc = _make_service()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    svc.get_or_create_for_chat = AsyncMock(return_value=(uid, cid, False, None))
    svc.orchestrator.handle_message.return_value = "Maya reply"

    await svc.handle_update(
        {"message": {"chat": {"id": 99}, "from": {"first_name": "Sam"}, "text": "hey"}}
    )

    svc.orchestrator.handle_message.assert_awaited_once_with(uid, cid, "hey")
    svc.client.send_message.assert_awaited_with(99, "Maya reply")


@pytest.mark.asyncio
async def test_handle_update_new_user_gets_greeting():
    svc = _make_service()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    svc.get_or_create_for_chat = AsyncMock(return_value=(uid, cid, True, "Hi, I'm Maya"))

    await svc.handle_update({"message": {"chat": {"id": 7}, "text": "/start"}})

    svc.client.send_message.assert_awaited_once_with(7, "Hi, I'm Maya")
    svc.orchestrator.handle_message.assert_not_called()


# ─────────────────────────── webhook route ───────────────────────────


def _client_with_service(monkeypatch, fake_service):
    from fastapi.testclient import TestClient

    import maya.web as web

    monkeypatch.setattr(web, "get_telegram_service", lambda: fake_service)
    settings = web.get_settings()
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret", raising=False)
    return TestClient(web.app)


def test_webhook_rejects_bad_secret(monkeypatch):
    fake = AsyncMock()
    tc = _client_with_service(monkeypatch, fake)
    resp = tc.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 1}, "text": "hi"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 403
    fake.handle_update.assert_not_called()


def test_webhook_dispatches_on_valid_secret(monkeypatch):
    fake = AsyncMock()
    tc = _client_with_service(monkeypatch, fake)
    payload = {"message": {"chat": {"id": 1}, "text": "hi"}}
    resp = tc.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    fake.handle_update.assert_awaited_once_with(payload)


# ─────────────────────────── service: DB mapping ───────────────────────────


from tests.conftest import db_required  # noqa: E402


@db_required
@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_per_chat(db_sessionmaker, monkeypatch):
    """First call creates user+companion (+genesis); repeat returns the same pair."""

    class _Genesis:
        first_message = "Hi, I'm Maya"

    async def _fake_genesis(companion_id, *, sessionmaker=None, llm=None):
        return _Genesis()

    monkeypatch.setattr(service_mod, "run_genesis", _fake_genesis)

    svc = TelegramService(client=AsyncMock(), sessionmaker=db_sessionmaker)

    uid1, cid1, created1, first1 = await svc.get_or_create_for_chat(
        555, first_name="Sam", username="sammy"
    )
    assert created1 is True
    assert first1 == "Hi, I'm Maya"

    uid2, cid2, created2, first2 = await svc.get_or_create_for_chat(555)
    assert created2 is False
    assert (uid2, cid2) == (uid1, cid1)
    assert first2 is None
