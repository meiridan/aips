"""Creation-wizard HTTP surface. Mirrors test_web_response_length.py: module-level
names in maya.web are monkeypatched, so no DB and no LLM call."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import maya.web as web
from maya.companions.onboarding import AlreadyOnboarded

UID, CID = uuid.uuid4(), uuid.uuid4()

VALID_SPEC = {
    "name": "מאיה",
    "age": 24,
    "style": "realistic",
    "ethnicity": "arab",
    "hair_style": "long",
    "hair_color": "blue",
    "eye_color": "hazel",
    "body_type": "curvy",
    "breast_size": "large",
    "butt_size": "large",
    "personality": "caregiver",
    "relationship": "girlfriend",
    "occupation": "nurse",
    "clothing": "cheerleader",
    "voice_style": "soft",
    "hobbies": ["yoga"],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "resolve_singleton", AsyncMock(return_value=(UID, CID, False, None)))
    return TestClient(web.app)


def test_catalog_is_served(client):
    body = client.get("/api/catalog").json()
    assert "ethnicity" in body["groups"]
    assert body["groups"]["ethnicity"]["options"][0]["he"]
    assert len(body["steps"]) == 6


def test_get_companion_before_onboarding(client, monkeypatch):
    monkeypatch.setattr(
        web,
        "get_state",
        AsyncMock(return_value={"onboarded": False, "name": "Maya", "spec": None}),
    )
    body = client.get("/api/companion").json()
    assert body["onboarded"] is False
    assert body["spec"] is None


def test_get_companion_after_onboarding(client, monkeypatch):
    monkeypatch.setattr(
        web,
        "get_state",
        AsyncMock(return_value={"onboarded": True, "name": "מאיה", "spec": VALID_SPEC}),
    )
    body = client.get("/api/companion").json()
    assert body["onboarded"] is True
    assert body["spec"]["ethnicity"] == "arab"


def test_post_valid_spec_creates_companion(client, monkeypatch):
    create = AsyncMock(return_value="היי, מה קורה?")
    monkeypatch.setattr(web, "create_companion", create)

    body = client.post("/api/companion", json=VALID_SPEC).json()
    assert body == {"ok": True, "first_message": "היי, מה קורה?"}

    _sm, companion_id, spec = create.await_args.args
    assert companion_id == CID
    assert spec.name == "מאיה"
    assert create.await_args.kwargs["reset"] is False


def test_reset_flag_is_forwarded(client, monkeypatch):
    create = AsyncMock(return_value="שלום")
    monkeypatch.setattr(web, "create_companion", create)

    client.post("/api/companion", json={**VALID_SPEC, "reset": True})
    assert create.await_args.kwargs["reset"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"ethnicity": "martian"},
        {"age": 12},
        {"personality": "nope"},
        {"hobbies": ["quidditch"]},
    ],
)
def test_post_invalid_option_is_422(client, monkeypatch, bad):
    monkeypatch.setattr(web, "create_companion", AsyncMock(return_value=None))
    resp = client.post("/api/companion", json={**VALID_SPEC, **bad})
    assert resp.status_code == 422


def test_post_missing_field_is_422(client):
    payload = {k: v for k, v in VALID_SPEC.items() if k != "ethnicity"}
    assert client.post("/api/companion", json=payload).status_code == 422


def test_post_when_already_onboarded_is_409(client, monkeypatch):
    monkeypatch.setattr(web, "create_companion", AsyncMock(side_effect=AlreadyOnboarded(str(CID))))
    resp = client.post("/api/companion", json=VALID_SPEC)
    assert resp.status_code == 409
    assert "reset" in resp.json()["detail"]


def test_index_reports_unbuilt_spa(client, monkeypatch, tmp_path):
    monkeypatch.setattr(web, "STATIC_DIR", tmp_path)
    resp = client.get("/")
    assert resp.status_code == 503
    assert "make ui" in resp.text
