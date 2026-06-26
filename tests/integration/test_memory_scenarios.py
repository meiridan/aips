"""Comprehensive memory scenarios — user facts AND companion-leak prevention.

Covers the regression behind the "Maya's biography stored as the user's facts"
bug: `extract_and_store` must extract ONLY from the user's message, never from
Maya's role-played self-disclosure.

Requires running Postgres (pgvector) + OpenAI + Grok. Skipped if env not set.
Run locally:  make dev  &&  uv run pytest tests/integration/test_memory_scenarios.py -v
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("XAI_API_KEY")),
    reason="Requires OPENAI_API_KEY + XAI_API_KEY",
)

# Maya's role-played persona — must NEVER end up as user facts.
MAYA_BIO = (
    "I'm Maya, 45 years old, blonde and divorced. I have three children — "
    "Yaheli, Ofri and Dor. I used to live in Har Adar. After my long divorce "
    "I rediscovered myself, started running alone on the beach, felt alive again."
)
# Tokens that, if found in USER memory, prove Maya's bio leaked.
MAYA_LEAK_TOKENS = [
    "yaheli", "ofri", "dor", "har adar", "divorced", "blonde", "45",
]


def _joined(mems: list[dict]) -> str:
    return " ".join(m["text"].lower() for m in mems)


def _assert_no_maya_leak(mems: list[dict]) -> None:
    text = _joined(mems)
    leaked = [t for t in MAYA_LEAK_TOKENS if t in text]
    assert not leaked, f"Maya's bio leaked into USER memory: {leaked}\n{text}"


@pytest.fixture(autouse=True)
async def _fresh_engine():
    """Each test runs in its own event loop; dispose the global async engine
    before and after so asyncpg connections are never reused across loops
    (otherwise: 'another operation is in progress')."""
    from maya.db.session import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


async def _svc():
    import maya  # noqa: F401  triggers SSL patch
    from maya.memory.service import MemoryService

    return MemoryService()


# ───────────────────────── USER-FACT SCENARIOS ─────────────────────────


@pytest.mark.asyncio
async def test_basic_user_fact_recall():
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        facts = await svc.extract_and_store(
            uid, cid, "My name is Idan and I work at Radware.",
            "Nice to meet you, Idan!",
        )
        assert facts, "should extract at least one user fact"
        res = await svc.search_relevant("where does he work?", uid, cid, limit=5)
        assert "radware" in _joined(res)
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_semantic_recall_different_wording():
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(
            uid, cid, "I love hiking trails in the Carmel on weekends.",
            "That sounds peaceful.",
        )
        res = await svc.search_relevant("what does he do outdoors?", uid, cid, limit=5)
        t = _joined(res)
        assert any(w in t for w in ("carmel", "hiking", "trail", "outdoor"))
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_multilingual_hebrew_recall():
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(
            uid, cid, "קוראים לי עידן ואני גר ברעננה.",
            "נעים מאוד עידן!",
        )
        res = await svc.search_relevant("where does he live?", uid, cid, limit=5)
        t = _joined(res)
        assert "עידן" in t or "idan" in t
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_dedup_repeated_fact():
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(uid, cid, "I love coffee.", "Same!")
        await svc.extract_and_store(uid, cid, "Did I say I love coffee?", "You did.")
        await svc.extract_and_store(uid, cid, "Coffee is my favorite drink.", "Noted.")
        await asyncio.sleep(0.5)
        mems = await svc.get_all(uid, cid)
        coffee = [m for m in mems if "coffee" in m["text"].lower()]
        assert len(coffee) <= 2, f"dedup failed: {coffee}"
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_contradiction_update():
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(uid, cid, "I work at Google.", "Cool.")
        await asyncio.sleep(0.3)
        await svc.extract_and_store(
            uid, cid, "I quit Google, now I work at Anthropic.", "Big move!",
        )
        await asyncio.sleep(0.5)
        res = await svc.search_relevant("where does he work now?", uid, cid, limit=10)
        t = _joined(res)
        assert "anthropic" in t, f"updated fact missing: {t}"
    finally:
        await svc.delete_all(uid, cid)


# ─────────────────── COMPANION-LEAK PREVENTION (regression) ───────────────────


@pytest.mark.asyncio
async def test_maya_self_disclosure_does_not_pollute_user_memory():
    """THE regression: Maya's role-played bio must not become user facts."""
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(
            uid, cid,
            user_message="Tell me about yourself.",
            assistant_message=MAYA_BIO,
        )
        await asyncio.sleep(0.5)
        _assert_no_maya_leak(await svc.get_all(uid, cid))
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_user_and_maya_kids_not_mixed():
    """User's real kids must be stored; Maya's kids must not appear as user's."""
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        await svc.extract_and_store(
            uid, cid,
            user_message="I have three kids: Arbel, Kinneret and Marom.",
            assistant_message="Lovely names! I have my own three — Yaheli, Ofri and Dor.",
        )
        await asyncio.sleep(0.5)
        mems = await svc.get_all(uid, cid)
        t = _joined(mems)
        # user's real kids present
        assert any(k in t for k in ("arbel", "kinneret", "marom")), t
        # Maya's kids must NOT be attributed to the user
        assert not any(k in t for k in ("yaheli", "ofri", "dor")), f"Maya kids leaked: {t}"
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_user_asks_maya_about_herself_memory_stays_clean():
    """A whole exchange about Maya's persona — user memory must stay user-only."""
    svc = await _svc()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    try:
        # Real user fact first
        await svc.extract_and_store(
            uid, cid, "By the way, my name is Idan.", "Hi Idan!",
        )
        # Then several turns where Maya talks about herself
        await svc.extract_and_store(
            uid, cid, "How old are you?", "I'm 45, divorced, blonde.",
        )
        await svc.extract_and_store(
            uid, cid, "Where did you grow up?", "Har Adar, with my kids Yaheli, Ofri, Dor.",
        )
        await asyncio.sleep(0.5)
        mems = await svc.get_all(uid, cid)
        # user fact retained
        assert "idan" in _joined(mems)
        # none of Maya's bio leaked
        _assert_no_maya_leak(mems)
    finally:
        await svc.delete_all(uid, cid)
