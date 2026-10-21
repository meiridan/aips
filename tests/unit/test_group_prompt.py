"""Group chat prompt assembly, the speaker-POV transcript and the reply guard."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from maya.conversation.moment_analyzer import default_moment
from maya.conversation.prompt_builder import (
    GROUP_SYSTEM_TEMPLATE,
    PHASE3_SYSTEM_TEMPLATE,
    GroupLine,
    OtherMember,
    build_group_phase3,
    render_group_turns,
)
from maya.conversation.reply_guard import ReplyGuard

MAYA = uuid.uuid4()
LILA = uuid.uuid4()


def _lines():
    return [
        GroupLine(None, "עידן", "היי בנות"),
        GroupLine(MAYA, "מאיה", "היי אהוב"),
        GroupLine(LILA, "לילה", "סוף סוף הוא כאן"),
        GroupLine(None, "עידן", "מה עשיתן היום?"),
    ]


def test_own_lines_are_assistant_and_everyone_else_is_named():
    turns = render_group_turns(_lines(), MAYA)
    assert turns == [
        {"role": "user", "content": "[עידן]: היי בנות"},
        {"role": "assistant", "content": "היי אהוב"},
        # Lila and the user back to back: one merged user turn, not two.
        {"role": "user", "content": "[לילה]: סוף סוף הוא כאן\n[עידן]: מה עשיתן היום?"},
    ]


def test_the_same_room_from_the_other_seat():
    turns = render_group_turns(_lines(), LILA)
    assert turns[0] == {"role": "user", "content": "[עידן]: היי בנות\n[מאיה]: היי אהוב"}
    assert turns[1] == {"role": "assistant", "content": "סוף סוף הוא כאן"}
    assert turns[-1]["role"] == "user"


def test_group_template_reuses_the_solo_sections():
    """The shared sections must be the same text in both, not copies that drift."""
    from maya.conversation import prompt_builder as pb

    for section in (pb._WHO_YOU_ARE, pb._FEELINGS, pb._MEMORIES, pb._HOW_TO_RESPOND):
        assert section in PHASE3_SYSTEM_TEMPLATE
        assert section in GROUP_SYSTEM_TEMPLATE
    assert pb._DESIRE not in GROUP_SYSTEM_TEMPLATE  # the 1:1 block is written for a couple


def test_build_group_phase3_tells_her_who_is_in_the_room():
    companion = SimpleNamespace(
        id=MAYA,
        name="מאיה",
        personality={"description": "a designer"},
        backstory="",
        locale="he",
        response_length=2,
    )
    prompt = build_group_phase3(
        companion=companion,
        others=[OtherMember("לילה", "a dancer", "met Maya at school")],
        room_dynamics="Best friends.",
        memories=[],
        emotional=SimpleNamespace(feelings={}, valence=0.0, arousal=0.5),
        relationship=SimpleNamespace(
            days_known=1, stage="strangers", intimacy_level=1, trust_level=1
        ),
        commitments=[],
        moment=default_moment(),
        lines=_lines(),
        user_name="עידן",
        turn_note="עידן's last message was to all of you.",
    )
    system = prompt[0]["content"]
    assert system.startswith("You are מאיה, an AI companion, in a group chat with עידן and לילה")
    assert "═══ WHO ELSE IS HERE ═══\nBest friends." in system
    assert "About לילה: a dancer" in system
    assert "met Maya at school" in system
    assert "never write lines for עידן or לילה" in system
    assert "עידן's last message was to all of you." in system
    assert "Write every reply in Hebrew" in system
    # The room counts sentences; the 1:1 word target never reaches it.
    assert "Keep each message to 3–5 sentences" in system
    assert "words, unless a crisis" not in system
    assert prompt[-1]["role"] == "user"


# ─────────────────────────────── reply guard ────────────────────────────────


def _run(guard: ReplyGuard, chunks: list[str]) -> str:
    out = "".join(guard.feed(c) for c in chunks)
    return out + guard.finish()


def test_guard_passes_a_normal_reply_through():
    guard = ReplyGuard("מאיה", ["לילה", "עידן"])
    assert _run(guard, ["הי", "י אהוב", "\nמה ", "שלומך?"]) == "היי אהוב\nמה שלומך?"
    assert not guard.stopped


def test_guard_releases_text_as_it_streams():
    guard = ReplyGuard("מאיה", ["לילה"])
    assert guard.feed("שלום לך, איך עבר היום") == "שלום לך, איך עבר היום"


def test_guard_strips_her_own_name_split_across_chunks():
    guard = ReplyGuard("מאיה", ["לילה"])
    assert _run(guard, ["מא", "יה: ", "היי"]) == "היי"


def test_guard_cuts_where_she_starts_writing_her_friend():
    guard = ReplyGuard("מאיה", ["לילה", "עידן"])
    assert _run(guard, ["ברור שכן\nלי", "לה: ואני", " מסכימה"]) == "ברור שכן"
    assert guard.stopped


def test_guard_cuts_the_bracketed_form_and_the_user():
    assert _run(ReplyGuard("מאיה", ["לילה", "עידן"]), ["כן!\n[עידן]: באמת?"]) == "כן!"


def test_guard_drops_a_reply_that_opens_as_someone_else():
    guard = ReplyGuard("מאיה", ["לילה"])
    assert _run(guard, ["לילה: אני", " בכלל לא מאיה"]) == ""
    assert guard.stopped


def test_guard_keeps_a_line_that_merely_mentions_a_name():
    guard = ReplyGuard("מאיה", ["לילה"])
    assert _run(guard, ["אמרתי לה\nלילה תמיד צוחקת"]) == "אמרתי לה\nלילה תמיד צוחקת"
