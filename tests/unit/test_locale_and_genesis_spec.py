"""Reply-language directive (shared by web + Telegram) and spec-aware genesis."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maya.conversation.prompt_builder import build_phase3, language_directive

HEBREW_MARKER = "in Hebrew"


def _companion(locale="he", **over):
    base = dict(
        name="מאיה",
        personality={"description": "She is a caregiver."},
        backstory="נולדתי בחיפה.",
        locale=locale,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _system(**over):
    kwargs = dict(
        companion=_companion(),
        memories=[],
        emotional=SimpleNamespace(feelings={"warm": 0.5}, valence=0.3, arousal=0.5),
        relationship=SimpleNamespace(
            days_known=1, stage="strangers", intimacy_level=1, trust_level=1
        ),
        commitments=[],
        moment=SimpleNamespace(moment_type="chitchat", character_priority="presence_and_comfort"),
        recent_msgs=[],
        user_name="Idan",
    )
    kwargs.update(over)
    return build_phase3(**kwargs)[0]["content"]


# ───────────────────────────── language directive ────────────────────────────


def test_hebrew_locale_adds_directive():
    assert HEBREW_MARKER in _system()


@pytest.mark.parametrize("locale", ["en", "", None])
def test_other_locales_add_nothing(locale):
    assert HEBREW_MARKER not in _system(companion=_companion(locale=locale))


def test_companion_without_locale_attribute_is_safe():
    bare = SimpleNamespace(name="Maya", personality={}, backstory="")
    assert HEBREW_MARKER not in _system(companion=bare)


def test_language_directive_is_case_insensitive():
    assert language_directive("HE") == language_directive("he") != ""


def test_persona_description_reaches_the_prompt():
    comp = _companion(personality={"description": "She is a 24-year-old Arab nurse."})
    assert "24-year-old Arab nurse" in _system(companion=comp)


# ──────────────────────────── genesis with a spec ────────────────────────────


def _spec():
    from maya.companions.persona_spec import PersonaSpec

    return PersonaSpec(
        name="מאיה",
        age=24,
        style="realistic",
        ethnicity="arab",
        hair_style="long",
        hair_color="blue",
        eye_color="hazel",
        body_type="curvy",
        breast_size="large",
        butt_size="large",
        personality="caregiver",
        relationship="girlfriend",
        occupation="nurse",
        clothing="cheerleader",
        voice_style="soft",
        hobbies=["yoga"],
    )


class _CapturingLLM:
    def __init__(self):
        self.prompt: str | None = None

    async def chat_json(self, messages, **kwargs):
        self.prompt = messages[0]["content"]
        return {
            "backstory": "נולדתי בחיפה.",
            "initial_feelings": {"valence": 0.3, "arousal": 0.4, "feelings": {}},
            "seed_commitments": [],
            "first_message": "היי",
        }


async def test_genesis_prompt_carries_spec_and_hebrew_instruction():
    from maya.companions.genesis import generate_genesis

    llm = _CapturingLLM()
    companion = SimpleNamespace(name="מאיה", template_id="devoted", locale="he")
    user = SimpleNamespace(name="Idan", description="curious")

    await generate_genesis(companion, user, llm, spec=_spec())

    assert "24-year-old Arab" in llm.prompt
    assert "never contradict it" in llm.prompt
    assert "in Hebrew" in llm.prompt


async def test_genesis_without_spec_keeps_legacy_prompt():
    from maya.companions.genesis import generate_genesis

    llm = _CapturingLLM()
    companion = SimpleNamespace(name="Maya", template_id="flirt", locale="en")
    user = SimpleNamespace(name="Idan", description=None)

    await generate_genesis(companion, user, llm)

    assert "never contradict it" not in llm.prompt
    assert "in Hebrew" not in llm.prompt
    assert "The Flirt" not in llm.prompt  # description, not the display name
    assert "Playful, teasing" in llm.prompt
