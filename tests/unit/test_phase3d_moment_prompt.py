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


def test_prompt_guards_against_abrupt_tone_shift_after_vulnerability():
    # Bug 5: Maya pivoted to intimacy without acknowledging prior vulnerability.
    sys = _build()[0]["content"]
    assert "vulnerable" in sys.lower() or "crisis" in sys.lower()
    assert "acknowledgment" in sys.lower() or "honour" in sys.lower() or "honor" in sys.lower()
