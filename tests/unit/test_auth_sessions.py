"""Server-side sessions against a real Postgres schema."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from maya.auth import sessions
from maya.db.models import UserSession
from tests.conftest import db_required

pytestmark = db_required


async def _row(sm, token):
    async with sm() as s:
        return (
            await s.execute(
                select(UserSession).where(
                    UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
                )
            )
        ).scalar_one()


async def test_issue_returns_a_token_that_resolves(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    token = await sessions.issue(db_sessionmaker, user_id)
    assert await sessions.resolve(db_sessionmaker, token) == user_id


async def test_raw_token_is_never_stored(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    token = await sessions.issue(db_sessionmaker, user_id)
    async with db_sessionmaker() as s:
        stored = [r.token_hash for r in (await s.scalars(select(UserSession))).all()]
    assert token not in stored
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]


async def test_two_sessions_for_one_user_are_independent(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    a = await sessions.issue(db_sessionmaker, user_id)
    b = await sessions.issue(db_sessionmaker, user_id)
    assert a != b
    await sessions.revoke(db_sessionmaker, a)
    assert await sessions.resolve(db_sessionmaker, a) is None
    assert await sessions.resolve(db_sessionmaker, b) == user_id


async def test_unknown_and_empty_tokens_resolve_to_none(db_sessionmaker):
    assert await sessions.resolve(db_sessionmaker, "nope") is None
    assert await sessions.resolve(db_sessionmaker, "") is None
    assert await sessions.resolve(db_sessionmaker, None) is None


async def test_expired_session_resolves_to_none(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    token = await sessions.issue(db_sessionmaker, user_id)
    async with db_sessionmaker() as s:
        row = await s.get(UserSession, (await _row(db_sessionmaker, token)).id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    assert await sessions.resolve(db_sessionmaker, token) is None


async def test_revoke_all_kills_every_session(db_sessionmaker, seeded_ids):
    """What a password reset relies on."""
    user_id, _ = seeded_ids
    tokens = [await sessions.issue(db_sessionmaker, user_id) for _ in range(3)]
    await sessions.revoke_all(db_sessionmaker, user_id)
    for token in tokens:
        assert await sessions.resolve(db_sessionmaker, token) is None


async def test_revoking_an_unknown_token_is_a_noop(db_sessionmaker):
    await sessions.revoke(db_sessionmaker, "not-a-real-token")
    await sessions.revoke(db_sessionmaker, None)


async def test_expiry_slides_only_once_per_window(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    token = await sessions.issue(db_sessionmaker, user_id)
    first = await _row(db_sessionmaker, token)
    original_seen, original_exp = first.last_seen_at, first.expires_at

    # Fresh session: a read must not write.
    await sessions.resolve(db_sessionmaker, token)
    assert (await _row(db_sessionmaker, token)).last_seen_at == original_seen

    # Stale session: the read slides the window forward.
    async with db_sessionmaker() as s:
        row = await s.get(UserSession, first.id)
        row.last_seen_at = datetime.now(UTC) - timedelta(hours=2)
        await s.commit()
    await sessions.resolve(db_sessionmaker, token)
    assert (await _row(db_sessionmaker, token)).expires_at > original_exp


async def test_sessions_are_scoped_to_their_own_user(db_sessionmaker, seeded_ids):
    """The whole point of the table: one cookie must never resolve to another
    account."""
    from maya.db.models import User

    user_a, _ = seeded_ids
    async with db_sessionmaker() as s:
        other = User(name="Someone Else")
        s.add(other)
        await s.commit()
        user_b = other.id

    token_a = await sessions.issue(db_sessionmaker, user_a)
    token_b = await sessions.issue(db_sessionmaker, user_b)
    assert await sessions.resolve(db_sessionmaker, token_a) == user_a
    assert await sessions.resolve(db_sessionmaker, token_b) == user_b


def test_cookie_is_httponly_and_lax():
    params = sessions.cookie_params()
    assert params["httponly"] is True
    assert params["samesite"] == "lax"
    assert params["path"] == "/"


@pytest.mark.parametrize("environment,expected_secure", [("local", False), ("production", True)])
def test_cookie_secure_follows_environment(monkeypatch, environment, expected_secure):
    from maya.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", environment)
    try:
        assert sessions.cookie_params()["secure"] is expected_secure
        assert Settings().environment == environment
    finally:
        get_settings.cache_clear()
