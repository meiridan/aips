"""Response-length mapping + parsing, prompt injection, and the persist helper."""

from __future__ import annotations

import pytest

from maya.conversation import response_length as rl
from tests.conftest import db_required

# ── mapping / parsing ─────────────────────────────────────────────────────


def test_words_and_tokens_per_level():
    assert (rl.words_for(1), rl.max_tokens_for(1)) == (100, 250)
    assert (rl.words_for(2), rl.max_tokens_for(2)) == (300, 700)
    assert (rl.words_for(3), rl.max_tokens_for(3)) == (1000, 1600)


def test_normalize_clamps_and_defaults():
    assert rl.normalize(2) == 2
    assert rl.normalize(0) == rl.DEFAULT
    assert rl.normalize(9) == rl.DEFAULT
    assert rl.normalize("nope") == rl.DEFAULT
    assert rl.normalize(None) == rl.DEFAULT
    assert rl.normalize("3") == 3  # numeric strings coerce


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", 1), ("2", 2), ("3", 3),
        ("short", 1), ("Medium", 2), (" LONG ", 3),
        ("", None), ("huge", None), ("4", None),
    ],
)
def test_parse(text, expected):
    assert rl.parse(text) == expected


def test_labels():
    assert (rl.label(1), rl.label(2), rl.label(3)) == ("short", "medium", "long")


# ── prompt injection ──────────────────────────────────────────────────────


def _min_build(level):
    from types import SimpleNamespace

    from maya.conversation.prompt_builder import build_phase3

    companion = SimpleNamespace(name="Maya", personality={}, backstory="")
    emotional = SimpleNamespace(feelings={}, valence=0.0, arousal=0.5)
    relationship = SimpleNamespace(
        days_known=0, stage="strangers", intimacy_level=1, trust_level=1
    )
    moment = SimpleNamespace(
        moment_type="chitchat", character_priority="presence", guidance=lambda: ""
    )
    return build_phase3(
        companion=companion, memories=[], emotional=emotional,
        relationship=relationship, commitments=[], moment=moment,
        recent_msgs=[], user_name="Sam", response_length=level,
    )[0]["content"]


@pytest.mark.parametrize("level,words", [(1, 100), (2, 300), (3, 1000)])
def test_prompt_states_word_target(level, words):
    system = _min_build(level)
    assert f"roughly {words} words" in system


# ── persist helper ────────────────────────────────────────────────────────


@db_required
@pytest.mark.asyncio
async def test_set_response_length_persists_and_invalidates(db_sessionmaker, seeded_ids):
    from maya import runtime_cache
    from maya.companions.settings import set_response_length
    from maya.db.models import Companion

    _uid, cid = seeded_ids
    # Prime the cache with a stale copy, then change the level.
    async with db_sessionmaker() as s:
        runtime_cache.set_companion(cid, await s.get(Companion, cid))

    stored = await set_response_length(db_sessionmaker, cid, "long")
    assert stored == 3
    assert runtime_cache.get_companion(cid) is None  # invalidated

    async with db_sessionmaker() as s:
        assert (await s.get(Companion, cid)).response_length == 3

    # Invalid input clamps to default rather than raising.
    assert await set_response_length(db_sessionmaker, cid, "bogus") == rl.DEFAULT
