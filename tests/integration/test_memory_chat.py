"""P2.5 integration test: Maya recalls a fact stated earlier in conversation.

Requires running Postgres + OpenAI + Grok. Skipped if env not set.
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


@pytest.mark.asyncio
async def test_companion_recalls_fact_via_memory():
    """Store a fact, search for it with different wording, expect semantic recall."""
    import maya  # noqa: F401  triggers SSL patch
    from maya.memory.service import MemoryService

    svc = MemoryService()
    uid = uuid.uuid4()
    cid = uuid.uuid4()

    try:
        facts = await svc.extract_and_store(
            user_id=uid,
            companion_id=cid,
            user_message="My name is David and I work as a backend developer at a fintech startup",
            assistant_message="Nice to meet you, David! Backend at a fintech sounds intense.",
        )
        assert facts, "Mem0 should extract at least one fact"

        results = await svc.search_relevant(
            query="what do I do for a living?",
            user_id=uid,
            companion_id=cid,
            limit=5,
        )
        assert results, "Search should return at least one memory"
        joined = " ".join(r["text"].lower() for r in results)
        assert "backend" in joined or "developer" in joined or "fintech" in joined
    finally:
        await svc.delete_all(uid, cid)


@pytest.mark.asyncio
async def test_memory_dedup():
    """Repeating a fact across messages should not produce many duplicates."""
    import maya  # noqa: F401
    from maya.memory.service import MemoryService

    svc = MemoryService()
    uid = uuid.uuid4()
    cid = uuid.uuid4()

    try:
        await svc.extract_and_store(uid, cid, "I love coffee", "Same here!")
        await svc.extract_and_store(
            uid, cid, "Did I mention I love coffee?", "Yes you did :)"
        )
        await svc.extract_and_store(
            uid, cid, "Coffee is my favorite drink", "Noted."
        )
        await asyncio.sleep(0.5)
        all_mems = await svc.get_all(uid, cid)
        coffee = [m for m in all_mems if "coffee" in m["text"].lower()]
        assert len(coffee) <= 2, f"Expected dedup, got {len(coffee)}: {coffee}"
    finally:
        await svc.delete_all(uid, cid)
