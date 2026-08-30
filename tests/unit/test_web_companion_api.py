"""Creation-wizard HTTP surface. Mirrors test_web_response_length.py: module-level
names in maya.web are monkeypatched, so no DB and no LLM call."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import maya.web as web
from maya.auth.deps import current_user
from maya.companions.onboarding import AlreadyOnboarded
from maya.db.models import User

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
    """Signed in, with the data layer mocked — no DB, no LLM call."""
    monkeypatch.setattr(web, "resolve_for_user", AsyncMock(return_value=CID))
    web.app.dependency_overrides[current_user] = lambda: User(id=UID, name="Tester")
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """Signed out. The auth dependency is left in place."""
    web.app.dependency_overrides.clear()
    return TestClient(web.app)


def test_catalog_is_served(client):
    body = client.get("/api/catalog").json()
    assert "ethnicity" in body["groups"]
    assert body["groups"]["ethnicity"]["options"][0]["he"]
    assert len(body["steps"]) == 6


def test_catalog_reports_which_sign_in_methods_exist(anon_client):
    """The login screen hides a Google button the server can't honour."""
    body = anon_client.get("/api/catalog").json()
    assert body["auth"]["google"] is False  # no credentials in the test env
    assert body["strings"]["login_title"]


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
        {"preset": "definitely-not-a-preset"},
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


# ─────────────────────── authentication is required ────────────────────────


def test_catalog_stays_public(anon_client):
    """The SPA needs its Hebrew strings to render the login screen itself."""
    assert anon_client.get("/api/catalog").status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/companion"),
        ("post", "/api/companion"),
        ("get", "/companion/response_length"),
        ("post", "/companion/response_length"),
    ],
)
def test_companion_routes_require_a_session(anon_client, method, path):
    # GET takes no body; only the POSTs need a payload to get past parsing.
    kwargs = {"json": VALID_SPEC} if method == "post" else {}
    resp = getattr(anon_client, method)(path, **kwargs)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "not_authenticated"


def test_companion_is_resolved_from_the_session_user(client, monkeypatch):
    """The route must ask for THIS user's companion, never a global one."""
    resolve = AsyncMock(return_value=CID)
    monkeypatch.setattr(web, "resolve_for_user", resolve)
    monkeypatch.setattr(
        web, "get_state", AsyncMock(return_value={"onboarded": False, "name": "Maya", "spec": None})
    )

    client.get("/api/companion")

    assert resolve.await_args.kwargs["user_id"] == UID


# ───────────────────────── SPA client routes ───────────────────────────────


@pytest.mark.parametrize("path", ["/login", "/signup", "/reset-password", "/subscription"])
def test_client_routes_serve_the_spa_shell(anon_client, path):
    """A reset link is opened cold from an email client, so a deep GET has to
    return the app shell, not a 404."""
    resp = anon_client.get(path)
    assert resp.status_code in (200, 503)  # 503 only when the bundle isn't built
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.parametrize(
    "path", ["/api/nope", "/companion/nope", "/auth/nope", "/billing/nope", "/telegram/nope"]
)
def test_unknown_server_paths_stay_404_json(anon_client, path):
    """Answering these with HTML would break the SPA's `json<T>()` handler."""
    resp = anon_client.get(path)
    assert resp.status_code == 404
    assert "text/html" not in resp.headers["content-type"]


def test_catch_all_does_not_shadow_a_real_route(anon_client):
    assert anon_client.get("/api/catalog").status_code == 200


# ──────────────────────── ready-made companions ─────────────────────────────


def test_catalog_carries_the_preset_gallery(anon_client):
    """The opening gallery renders from the public catalog — no extra endpoint."""
    body = anon_client.get("/api/catalog").json()
    presets = body["presets"]
    assert len(presets) == 9
    first = presets[0]
    assert first["name"] and first["tagline"] and first["bio"]
    assert first["portrait"].startswith("/media/presets/")
    assert len(first["gallery"]) == 4
    assert body["strings"]["preset_start"]


def test_posting_a_preset_creates_that_companion(client, monkeypatch):
    """Picking a preset is an ordinary spec POST — it skips the wizard, not the API."""
    from maya.companions import catalog

    create = AsyncMock(return_value="היי")
    monkeypatch.setattr(web, "create_companion", create)
    preset = catalog.PRESETS[0]

    resp = client.post(
        "/api/companion",
        json={**preset.spec, "name": preset.name, "preset": preset.id},
    )
    assert resp.status_code == 200

    _sm, _cid, spec = create.await_args.args
    assert spec.preset == preset.id
    assert spec.name == preset.name


def test_every_preset_is_postable(client, monkeypatch):
    from maya.companions import catalog

    monkeypatch.setattr(web, "create_companion", AsyncMock(return_value=None))
    for preset in catalog.PRESETS:
        resp = client.post(
            "/api/companion",
            json={**preset.spec, "name": preset.name, "preset": preset.id},
        )
        assert resp.status_code == 200, f"{preset.id}: {resp.text}"
