"""Group chat against a real schema, with a fake LLM and memory.

Covers the room lifecycle (partner creation, idempotence, wipe on re-creation)
and the turn itself: routing, order, the second speaker seeing the first, the
director and its caps, interruption, the reply guard, and that group lines never
reach the solo transcript.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from maya.companions import singleton
from maya.conversation import rooms
from maya.conversation.director import Director
from maya.conversation.group import GroupOrchestrator
from maya.conversation.group_settings import GroupSettings
from maya.db.models import Companion, Message
from tests.conftest import db_required

pytestmark = db_required

_MOMENT = {
    "moment_type": "chitchat",
    "emotional_intensity": 0.3,
    "emotional_delta": {
        "drop_feelings": [],
        "add_feelings": {},
        "valence_delta": 0.0,
        "arousal_delta": 0.0,
    },
    "character_priority": "presence_and_comfort",
    "detected_topics": [],
    "sensitive_flags": [],
}


class _FakeLLM:
    """Answers as whoever the system prompt says she is."""

    def __init__(
        self, scripts: dict[str, list[str]] | None = None, director: list[str] | None = None
    ):
        self.scripts = scripts or {}
        self.director = list(director or [])
        self.prompts: list[list[dict]] = []

    async def chat_stream(self, messages, **kwargs):
        self.prompts.append(messages)
        system = messages[0]["content"]
        speaker = "מאיה" if system.startswith("You are מאיה") else "לילה"
        queue = self.scripts.get(speaker)
        text = queue.pop(0) if queue else f"אני {speaker}"
        for i in range(0, len(text), 3):
            yield text[i : i + 3]

    async def chat_json(self, messages, **kwargs):
        prompt = messages[0]["content"]
        if "directing a group chat" in prompt:
            return {"next": self.director.pop(0) if self.director else "end"}
        if "analyzing a moment" in prompt:
            return dict(_MOMENT)
        return {"commitments": []}

    async def chat(self, messages, **kwargs):  # pragma: no cover - unused here
        return ""


class _FakeMemory:
    def __init__(self):
        self.extracted: list[tuple] = []

    async def search_relevant(self, *a, **k):
        return []

    async def extract_and_store(self, *, user_id, companion_id, user_message, assistant_message):
        self.extracted.append((companion_id, user_message))
        return []


def _orch(db_sessionmaker, llm, memory):
    from maya.companions.commitments import CommitmentService
    from maya.conversation.moment_analyzer import MomentAnalyzer
    from maya.conversation.orchestrator import Orchestrator
    from maya.emotional.service import EmotionalService
    from maya.relationship.service import RelationshipService

    return Orchestrator(
        llm=llm,
        memory=memory,
        sessionmaker=db_sessionmaker,
        emotional=EmotionalService(db_sessionmaker),
        relationship=RelationshipService(db_sessionmaker),
        commitments=CommitmentService(db_sessionmaker, llm=llm),
        moment_analyzer=MomentAnalyzer(llm),
    )


@pytest.fixture
def genesis_calls(monkeypatch):
    calls: list[dict] = []

    async def fake(companion_id, **kwargs):
        calls.append({"companion_id": companion_id, **kwargs})
        return SimpleNamespace(first_message="היי")

    monkeypatch.setattr(singleton, "run_genesis", fake)
    return calls


async def _onboard_primary(sm, cid):
    async with sm() as session:
        comp = await session.get(Companion, cid)
        comp.name = "מאיה"
        comp.persona_spec = {"preset": "maya"}
        comp.onboarded_at = datetime.now(UTC)
        await session.commit()


@pytest.fixture
async def room(db_sessionmaker, seeded_ids, genesis_calls):
    uid, cid = seeded_ids
    await _onboard_primary(db_sessionmaker, cid)
    return await singleton.resolve_group(db_sessionmaker, user_id=uid)


class _Events:
    def __init__(self):
        self.items: list[dict] = []

    async def __call__(self, payload):
        self.items.append(payload)

    def speakers(self):
        return [e["speaker"] for e in self.items if e["type"] == "message_start"]


# ─────────────────────────────── the room ───────────────────────────────────


async def test_room_needs_the_primary_companion_first(db_sessionmaker, seeded_ids, genesis_calls):
    uid, _ = seeded_ids
    with pytest.raises(singleton.CompanionNotOnboarded):
        await singleton.resolve_group(db_sessionmaker, user_id=uid)
    assert genesis_calls == []


async def test_room_creates_lila_once_and_seats_her_second(
    db_sessionmaker, seeded_ids, room, genesis_calls
):
    uid, cid = seeded_ids
    assert [m.slot for m in room.members] == ["primary", "lila"]
    assert room.members[0].companion_id == cid
    assert room.members[1].name == "לילה"
    assert room.members[1].handle == "lila"

    (call,) = genesis_calls
    assert call["conversation_id"] == room.conversation_id  # her hello lands in the room
    assert "מאיה" in call["group_context"]

    again = await singleton.resolve_group(db_sessionmaker, user_id=uid)
    assert again == room
    assert len(genesis_calls) == 1
    # The account's own companion is still the one resolve_for_user returns.
    from maya import runtime_cache

    runtime_cache.clear()
    assert await singleton.resolve_for_user(db_sessionmaker, user_id=uid) == cid


async def test_recreating_the_primary_clears_the_group_room(
    db_sessionmaker, seeded_ids, room, monkeypatch
):
    from maya.companions import onboarding
    from maya.companions.persona_spec import PersonaSpec

    uid, cid = seeded_ids
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, _FakeLLM(), _FakeMemory()), director_enabled=False
    )
    await orch.run_turn(room, "היי", emit=_Events())
    assert await rooms.load_transcript(db_sessionmaker, room.conversation_id, 50)

    async def fake_genesis(*a, **k):
        return SimpleNamespace(first_message="שלום")

    monkeypatch.setattr(onboarding, "run_genesis", fake_genesis)
    from maya.companions.catalog import PRESETS

    maya = PRESETS[0]
    spec = PersonaSpec(name=maya.name, preset=maya.id, **maya.spec)
    await onboarding.create_companion(db_sessionmaker, cid, spec, reset=True)
    assert await rooms.load_transcript(db_sessionmaker, room.conversation_id, 50) == []


# ─────────────────────────────── a turn ─────────────────────────────────────


async def test_both_answer_in_order_and_the_second_sees_the_first(db_sessionmaker, room):
    llm = _FakeLLM({"מאיה": ["בוקר טוב אהוב"], "לילה": ["ומה איתי?"]})
    memory = _FakeMemory()
    events = _Events()
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, llm, memory), director_enabled=False, min_ai_messages=1
    )

    spoken = await orch.run_turn(room, "בוקר טוב בנות", emit=events)

    assert [s.member.slot for s in spoken] == ["primary", "lila"]
    assert [s.content for s in spoken] == ["בוקר טוב אהוב", "ומה איתי?"]
    assert events.items[0] == {"type": "turn_start", "addressed": ["primary", "lila"]}
    assert events.items[-1] == {"type": "turn_end"}
    lila_prompt = llm.prompts[1]
    assert lila_prompt[-1] == {
        "role": "user",
        "content": "[Tester]: בוקר טוב בנות\n[מאיה]: בוקר טוב אהוב",
    }

    transcript = await rooms.load_transcript(db_sessionmaker, room.conversation_id, 50)
    user_turn = next(m for m in transcript if m.role == "user")
    assert user_turn.companion_id is None
    assert user_turn.extra["addressed"] == ["primary", "lila"]
    # Both heard him, so both remember what he said.
    assert {cid for cid, _ in memory.extracted} == {m.companion_id for m in room.members}


async def test_a_name_up_front_gets_only_her(db_sessionmaker, room):
    llm = _FakeLLM()
    events = _Events()
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, llm, _FakeMemory()), director_enabled=False, min_ai_messages=1
    )
    await orch.run_turn(room, "לילה, רק את", emit=events)
    assert events.speakers() == ["lila"]
    assert "was to you alone" in llm.prompts[0][0]["content"]


async def test_explicit_target_wins(db_sessionmaker, room):
    events = _Events()
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, _FakeLLM(), _FakeMemory()), director_enabled=False, min_ai_messages=1
    )
    await orch.run_turn(room, "לילה, רק את", target="primary", emit=events)
    assert events.speakers() == ["primary"]


async def test_whoever_spoke_last_opens_the_next_turn(db_sessionmaker, room):
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, _FakeLLM(), _FakeMemory()), director_enabled=False, min_ai_messages=1
    )
    first, second = _Events(), _Events()
    await orch.run_turn(room, "היי", emit=first)
    await orch.run_turn(room, "מה חדש", emit=second)
    assert first.speakers() == ["primary", "lila"]
    assert second.speakers() == ["lila", "primary"]


async def test_director_follow_ups_respect_the_caps(db_sessionmaker, room):
    # The director keeps asking for more; the ceiling and no-repeat rule hold.
    llm = _FakeLLM(
        {"מאיה": ["אחת", "שלוש", "חמש"], "לילה": ["שתיים", "ארבע"]},
        director=["lila", "primary", "lila"],
    )
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, llm, _FakeMemory()),
        director=Director(llm),
        max_ai_messages=3,
        min_ai_messages=1,
    )
    events = _Events()
    spoken = await orch.run_turn(room, "מאיה, ספרי לי", emit=events)
    assert [s.member.slot for s in spoken] == ["primary", "lila", "primary"]
    assert events.speakers() == ["primary", "lila", "primary"]


async def test_moderated_talk_goes_back_and_forth_before_the_director(db_sessionmaker, room):
    # Only Maya was named, yet they exchange three lines; then the director adds a fourth.
    llm = _FakeLLM(
        {"מאיה": ["תפוח ירוק", "שולחן עץ"], "לילה": ["ים כחול", "מנורה צהובה"]},
        director=["lila"],
    )
    orch = GroupOrchestrator(_orch(db_sessionmaker, llm, _FakeMemory()), director=Director(llm))
    events = _Events()
    await orch.run_turn(room, "מאיה, ספרי לי", emit=events)

    assert events.speakers() == ["primary", "lila", "primary", "lila"]
    assert llm.director == []
    assert "Keep each message to 1–3 sentences" in llm.prompts[0][0]["content"]
    assert "going back and forth" in llm.prompts[1][0]["content"]
    assert "going back and forth" not in llm.prompts[3][0]["content"]  # the director's pick


def _distinct_llm(director: list[str] | None = None) -> _FakeLLM:
    # Lines far enough apart that the near-repeat stop never fires.
    return _FakeLLM(
        {
            "מאיה": ["תפוח ירוק", "שולחן עץ", "חתול שחור", "רכבת לילה", "גשם חזק"],
            "לילה": ["ים כחול", "מנורה צהובה", "כלב קטן", "הר גבוה", "שמש חמה"],
        },
        director=director,
    )


async def test_free_talk_runs_to_the_safety_limit_without_the_director(db_sessionmaker, room):
    llm = _distinct_llm(director=["end"])
    orch = GroupOrchestrator(
        _orch(db_sessionmaker, llm, _FakeMemory()),
        director=Director(llm),
        free_talk_max_messages=5,
    )
    events = _Events()
    spoken = await orch.run_turn(
        room, "היי בנות", emit=events, settings=GroupSettings(talk_mode="free")
    )
    assert [s.member.slot for s in spoken] == ["primary", "lila", "primary", "lila", "primary"]
    assert llm.director == ["end"]  # never consulted


async def test_switching_to_moderated_mid_talk_stops_it(db_sessionmaker, room):
    settings = GroupSettings(talk_mode="free")
    events = _Events()

    async def emit(payload):
        await events(payload)
        if payload["type"] == "message_end" and len(events.speakers()) == 5:
            settings.apply({"talk_mode": "moderated"})  # toggled while she was talking

    orch = GroupOrchestrator(_orch(db_sessionmaker, _distinct_llm(), _FakeMemory()))
    spoken = await orch.run_turn(room, "היי בנות", emit=emit, settings=settings)
    assert len(spoken) == 5  # past the moderated ceiling of 4, so nobody else starts


async def test_a_new_message_ends_free_talk(db_sessionmaker, room):
    cancel = asyncio.Event()
    events = _Events()

    async def emit(payload):
        await events(payload)
        if payload["type"] == "message_end" and len(events.speakers()) == 3:
            cancel.set()

    orch = GroupOrchestrator(_orch(db_sessionmaker, _distinct_llm(), _FakeMemory()))
    spoken = await orch.run_turn(
        room, "היי בנות", emit=emit, cancel=cancel, settings=GroupSettings(talk_mode="free")
    )
    assert len(spoken) == 3


async def test_room_settings_are_saved_and_loaded(db_sessionmaker, seeded_ids, room):
    uid, _ = seeded_ids
    assert GroupSettings.from_dict(room.settings) == GroupSettings()
    await rooms.save_settings(
        db_sessionmaker, room.conversation_id, {"response_length": 3, "talk_mode": "free"}
    )
    again = await singleton.resolve_group(db_sessionmaker, user_id=uid)
    assert GroupSettings.from_dict(again.settings) == GroupSettings(3, "free")


async def test_a_near_repeat_ends_the_turn(db_sessionmaker, room):
    llm = _FakeLLM({"מאיה": ["כן כן כן"], "לילה": ["כן כן כן"]}, director=["primary"])
    orch = GroupOrchestrator(_orch(db_sessionmaker, llm, _FakeMemory()), director=Director(llm))
    spoken = await orch.run_turn(room, "נכון?", emit=_Events())
    assert len(spoken) == 2


async def test_a_new_message_stops_anyone_new_from_starting(db_sessionmaker, room):
    cancel = asyncio.Event()
    events = _Events()

    async def emit(payload):
        await events(payload)
        if payload["type"] == "message_end":
            cancel.set()  # the user typed while the first one was talking

    orch = GroupOrchestrator(
        _orch(db_sessionmaker, _FakeLLM(), _FakeMemory()), director_enabled=False
    )
    spoken = await orch.run_turn(room, "היי", emit=emit, cancel=cancel)
    assert len(spoken) == 1
    assert events.items[-1] == {"type": "turn_end"}


async def test_she_is_cut_off_before_speaking_for_her_friend(db_sessionmaker, room):
    llm = _FakeLLM({"מאיה": ["ברור!\nלילה: ואני מסכימה"]})
    orch = GroupOrchestrator(_orch(db_sessionmaker, llm, _FakeMemory()), director_enabled=False)
    spoken = await orch.run_turn(room, "מאיה, נכון?", emit=_Events())
    assert spoken[0].content == "ברור!"


async def test_group_lines_never_reach_the_solo_transcript(db_sessionmaker, seeded_ids, room):
    _uid, cid = seeded_ids
    base = _orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    await GroupOrchestrator(base, director_enabled=False, min_ai_messages=1).run_turn(
        room, "סוד קבוצתי", emit=_Events()
    )

    solo = await base._recent_messages_own(cid, 50)
    assert all("סוד" not in m.content for m in solo)
    async with db_sessionmaker() as session:
        her_group_lines = (
            await session.scalars(
                select(Message)
                .where(Message.companion_id == cid)
                .where(Message.conversation_id == room.conversation_id)
            )
        ).all()
    assert len(her_group_lines) == 1


# ─────────────────────────────── show-prompt ────────────────────────────────


async def test_show_prompt_previews_a_group_speaker_without_saving(db_sessionmaker, room):
    from maya.conversation.prompt_debug import build_group_dump

    base = _orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    dump = await build_group_dump(room.user_id, "לילה, מה נשמע?", speaker="lila", orchestrator=base)
    assert dump.system.startswith("You are לילה, an AI companion, in a group chat")
    assert dump.messages[-1] == {"role": "user", "content": "[Tester]: לילה, מה נשמע?"}
    assert dump.meta["addressed"] == ["lila"] and dump.meta["speaks"] is True
    assert "was to you alone" in dump.system
    assert await rooms.load_transcript(db_sessionmaker, room.conversation_id, 50) == []


async def test_show_prompt_names_the_real_members_on_a_bad_slot(db_sessionmaker, room):
    from maya.conversation.prompt_debug import build_group_dump

    base = _orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    with pytest.raises(LookupError, match="primary, lila"):
        await build_group_dump(room.user_id, "היי", speaker="nobody", orchestrator=base)


async def test_show_prompt_never_creates_a_room(db_sessionmaker, seeded_ids):
    from maya.conversation.prompt_debug import build_group_dump

    uid, _ = seeded_ids
    base = _orch(db_sessionmaker, _FakeLLM(), _FakeMemory())
    with pytest.raises(LookupError, match="no group room"):
        await build_group_dump(uid, "היי", speaker="lila", orchestrator=base)
