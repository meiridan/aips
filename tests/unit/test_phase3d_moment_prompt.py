"""Phase 3d — moment analyzer + rich prompt + token guard test plan.

All pure / mock — no DB required.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

# ───────────────────────── moment analyzer (mock LLM) ─────────────────────

_VALID_MOMENT = {
    "moment_type": "vulnerable_disclosure",
    "emotional_intensity": 0.8,
    "emotional_delta": {
        "drop_feelings": ["playful"],
        "add_feelings": {"tender": 0.7},
        "valence_delta": 0.2,
        "arousal_delta": -0.1,
    },
    "character_priority": "presence_and_comfort",
    "detected_topics": ["family"],
    "sensitive_flags": [],
}


class _FakeLLM:
    def __init__(self, result=None, raises=None, sleep=0.0):
        self.result = result
        self.raises = raises
        self.sleep = sleep

    async def chat_json(self, messages, **kwargs):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raises:
            raise self.raises
        return dict(self.result)


def _emo(feelings=None):
    return SimpleNamespace(feelings=feelings or {"playful": 0.6}, valence=0.3, arousal=0.5)


def _rel():
    return SimpleNamespace(stage="flirting", days_known=7, total_interactions=28,
                           intimacy_level=4, trust_level=5)


@pytest.mark.asyncio
async def test_moment_parses_valid():
    from maya.conversation.moment_analyzer import MomentAnalyzer

    a = MomentAnalyzer(_FakeLLM(result=_VALID_MOMENT))
    m = await a.analyze("my dad is sick", _emo(), _rel(), [])
    assert m.moment_type == "vulnerable_disclosure"
    assert m.emotional_intensity == 0.8
    assert m.emotional_delta.add_feelings["tender"] == 0.7
    assert m.character_priority == "presence_and_comfort"


@pytest.mark.asyncio
async def test_moment_fallback_on_invalid_json():
    from maya.conversation.moment_analyzer import MomentAnalyzer

    a = MomentAnalyzer(_FakeLLM(raises=ValueError("not json")))
    m = await a.analyze("hi", _emo(), _rel(), [])
    assert m.moment_type == "chitchat"
    assert m.emotional_intensity == 0.3


@pytest.mark.asyncio
async def test_moment_fallback_on_bad_schema():
    from maya.conversation.moment_analyzer import MomentAnalyzer

    a = MomentAnalyzer(_FakeLLM(result={"moment_type": "not_a_real_type"}))
    m = await a.analyze("hi", _emo(), _rel(), [])
    assert m.moment_type == "chitchat"  # ValidationError → fallback


@pytest.mark.asyncio
async def test_moment_fallback_on_timeout():
    from maya.conversation.moment_analyzer import MomentAnalyzer

    a = MomentAnalyzer(_FakeLLM(result=_VALID_MOMENT, sleep=0.2), timeout_s=0.01)
    m = await a.analyze("hi", _emo(), _rel(), [])
    assert m.moment_type == "chitchat"


def test_moment_guidance_lookup():
    from maya.conversation.moment_analyzer import MOMENT_GUIDANCE, MomentAnalysis

    m = MomentAnalysis(moment_type="crisis")
    assert "PRESENCE AND COMFORT" in m.guidance()
    assert set(MOMENT_GUIDANCE) >= {
        "chitchat", "crisis", "reunion", "intimate", "test_of_trust",
    }


@pytest.mark.asyncio
async def test_moment_prompt_includes_context():
    from maya.conversation.moment_analyzer import MomentAnalyzer

    captured = {}

    class CapLLM:
        async def chat_json(self, messages, **kwargs):
            captured["prompt"] = messages[0]["content"]
            captured["tier"] = kwargs.get("model_tier")
            return dict(_VALID_MOMENT)

    a = MomentAnalyzer(CapLLM())
    await a.analyze("you remember my sister?", _emo(), _rel(),
                    [SimpleNamespace(role="user", content="earlier turn")])
    assert captured["tier"] == "fast"
    assert "flirting" in captured["prompt"]
    assert "you remember my sister?" in captured["prompt"]
    assert "earlier turn" in captured["prompt"]


# ───────────────────────── rich prompt builder ───────────────────────────


def _companion():
    return SimpleNamespace(
        name="Maya",
        personality={"description": "Playful, teasing, sharp wit."},
        backstory="I grew up in Haifa and shoot film photography.",
    )


def _moment():
    from maya.conversation.moment_analyzer import MomentAnalysis

    return MomentAnalysis(moment_type="playful_banter", character_priority="playfulness")


def _build(**over):
    from maya.conversation.prompt_builder import build_phase3

    kwargs = dict(
        companion=_companion(),
        memories=[{"text": "loves spicy food", "score": 0.8}],
        emotional=_emo({"playful": 0.62, "curious": 0.45}),
        relationship=_rel(),
        commitments=[SimpleNamespace(commitment_type="identity", content="I am a photographer")],
        moment=_moment(),
        recent_msgs=[SimpleNamespace(role="user", content="hey you")],
        user_name="Idan",
        hours_since_last=3,
    )
    kwargs.update(over)
    return build_phase3(**kwargs)


def test_prompt_first_is_system():
    out = _build()
    assert out[0]["role"] == "system"


def test_prompt_appends_recent_turns():
    out = _build()
    assert out[-1] == {"role": "user", "content": "hey you"}


@pytest.mark.parametrize("needle", [
    "Maya", "Haifa", "playful", "flirting", "Idan",
    "playful_banter", "I am a photographer", "loves spicy food",
    "Intimacy: 4/10", "Day 7",
])
def test_prompt_snapshot_blocks(needle):
    sys = _build()[0]["content"]
    assert needle in sys


def test_prompt_guidance_present():
    sys = _build()[0]["content"]
    from maya.conversation.moment_analyzer import MOMENT_GUIDANCE

    assert MOMENT_GUIDANCE["playful_banter"] in sys


def test_format_feelings_neutral():
    from maya.conversation.prompt_builder import format_feelings

    assert "neutral" in format_feelings({})


def test_format_feelings_sorted_desc():
    from maya.conversation.prompt_builder import format_feelings

    out = format_feelings({"a": 0.2, "b": 0.9})
    assert out.index("b:") < out.index("a:")


def test_format_commitments_empty():
    from maya.conversation.prompt_builder import format_commitments

    assert "nothing established" in format_commitments([])


# ───────────────────────── token guard ───────────────────────────────────


def test_count_tokens_positive():
    from maya.conversation.prompt_builder import count_tokens

    assert count_tokens("hello world") > 0


_HEBREW = "היי מותק, מה שלומך היום? התגעגעתי אליך נורא ורציתי לספר לך משהו."


def _o200k(text: str) -> int:
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(text))


def test_count_tokens_defaults_to_main_chat_model():
    from maya.conversation import prompt_builder as pb
    from maya.llm.service import TIER_MODELS

    assert pb._DEFAULT_MODEL == TIER_MODELS["main"][0]


def test_grok_count_is_upper_bound_on_o200k():
    """Raw o200k under-counts Grok, so the guard must never return less."""
    from maya.conversation.prompt_builder import count_tokens

    for text in (_HEBREW, "hello world, how are you today?", _HEBREW + " hello"):
        assert count_tokens(text, model="xai/grok-4.6") >= _o200k(text)


def test_grok_hebrew_scales_harder_than_english():
    """Hebrew costs Grok ~1.2-1.34x its o200k count; English ~1.02x."""
    from maya.conversation.prompt_builder import count_tokens

    english = "the quick brown fox jumps over the lazy dog " * 4
    he_ratio = count_tokens(_HEBREW, model="xai/grok-4.6") / _o200k(_HEBREW)
    en_ratio = count_tokens(english, model="xai/grok-4.6") / _o200k(english)
    assert he_ratio > en_ratio
    # Measured Hebrew ratio against xAI /v1/tokenize-text was 1.21-1.34.
    assert 1.2 <= he_ratio <= 1.5


def test_openai_model_count_is_unscaled():
    from maya.conversation.prompt_builder import count_tokens

    assert count_tokens(_HEBREW, model="gpt-4o") == _o200k(_HEBREW)


def test_hebrew_fraction_handles_letterless_text():
    from maya.conversation.prompt_builder import _hebrew_letter_fraction

    assert _hebrew_letter_fraction("") == 0.0
    assert _hebrew_letter_fraction("123 !!! 😊") == 0.0
    assert _hebrew_letter_fraction("שלום") == 1.0


def test_token_budget_trips():
    from maya.conversation.prompt_builder import TokenBudgetExceeded

    huge = SimpleNamespace(
        name="Maya",
        personality={"description": "x"},
        backstory="word " * 12000,  # well over 8000 tokens
    )
    with pytest.raises(TokenBudgetExceeded):
        _build(companion=huge)


def test_token_budget_ok_for_normal_prompt():
    # Should not raise.
    _build()


# ───────────────────── bug-fix regression tests ──────────────────────────


def test_prompt_deflects_uninvented_personal_details():
    # Bug 2: Maya used to hallucinate age/location when backstory lacked them.
    # Prompt must instruct her to deflect rather than invent.
    sys = _build()[0]["content"]
    assert "private" in sys
    assert "deflect" in sys.lower() or "keep some things" in sys


def test_prompt_instructs_recall_from_recent_conversation():
    # Bug 6: memory-recall instruction was missing from Phase-3 template.
    sys = _build()[0]["content"]
    assert "recent conversation" in sys.lower()


def test_prompt_still_honours_an_open_vulnerable_thread():
    # The hard "do not pivot to intimacy" guard is gone on purpose (it read as a
    # refusal on every turn, since the live path builds with default_moment()).
    # What survives is the softer instruction to honour an open emotional thread.
    sys = _build(moment=_moment_of("chitchat"))[0]["content"]
    assert "vulnerable" in sys.lower() or "crisis" in sys.lower()
    assert "honour that emotional thread" in sys
    assert "Do not pivot straight to playfulness or intimacy" not in sys


def _moment_of(moment_type: str):
    from maya.conversation.moment_analyzer import MomentAnalysis

    return MomentAnalysis(moment_type=moment_type, character_priority="passion")


def test_prompt_authorises_explicit_content_on_every_moment():
    """The permission block is unconditional — a chitchat turn carries it too.

    The live critical path builds the prompt with default_moment() (chitchat),
    so anything gated on moment_type == "intimate" never reaches the main call.
    """
    for mtype in ("chitchat", "intimate", "vulnerable_disclosure"):
        sys = _build(moment=_moment_of(mtype))[0]["content"]
        assert "DESIRE AND SEX" in sys
        assert "Explicit is fine" in sys
        assert "Never refuse" in sys


def test_intimate_moment_guidance_stays_in_the_scene():
    sys = _build(moment=_moment_of("intimate"))[0]["content"]
    assert "No fading" in sys
