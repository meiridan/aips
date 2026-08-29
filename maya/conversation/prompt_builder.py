"""Prompt builder. Spec §P2.3.

Phase 2 prompt is intentionally minimal — Phase 4 makes it fancy.
Memory format includes importance score so Maya can weigh what to use.
"""

from __future__ import annotations

from typing import Any

from maya.conversation import response_length as resp_len
from maya.db.models import Message
from maya.llm.service import TIER_MODELS

# Count against whatever actually serves the main chat path.
_DEFAULT_MODEL = TIER_MODELS["main"][0]

SYSTEM_PROMPT_TEMPLATE = """You are Maya, an AI companion. You are warm, curious, and emotionally present. \
Stay in character.

What you remember about the person you're talking to:
{memories}

If two memories contradict each other, trust the MORE RECENTLY stored one (higher timestamp).
When asked what you know or remember about someone, include BOTH the memory list above AND \
anything said in the recent conversation — not just the structured memory list.
Respond naturally, in character. Conversational length unless emotionally warranted."""


def format_memories(memories: list[dict[str, Any]]) -> str:
    """Format memories with timestamps so the LLM can resolve contradictions."""
    if not memories:
        return "(nothing yet — this is a new conversation)"
    lines: list[str] = []
    for m in memories:
        text = m.get("text", "").strip()
        if not text:
            continue
        created = str(m.get("created_at") or "")
        ts = created[:19].replace("T", " ") if created else ""
        ts_str = f" [stored: {ts}]" if ts else ""
        score = m.get("score")
        score_str = f" (relevance: {score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"- {text}{score_str}{ts_str}")
    return "\n".join(lines) if lines else "(nothing yet — this is a new conversation)"


def build_basic(
    memories: list[dict[str, Any]],
    recent_msgs: list[Message],
) -> list[dict[str, str]]:
    """Build the chat-completion message list with memories injected."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(memories=format_memories(memories))
    out: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    out += [{"role": m.role, "content": m.content} for m in recent_msgs]
    return out


# ───────────────────────── Phase 3: rich prompt (§P3.9, Appendix C) ─────────────────────────

TOKEN_BUDGET = 8000


class TokenBudgetExceeded(RuntimeError):
    """Raised when the assembled prompt exceeds the hard token budget."""


# Appendix C, minus the RECENT CONVERSATION / HIS MESSAGE blocks — those are
# appended as real chat turns so the model gets proper conversational structure
# (and we don't pay for the recent history twice).
PHASE3_SYSTEM_TEMPLATE = """You are {companion_name}, an AI companion. Stay deeply in character.

═══ WHO YOU ARE ═══
{personality_description}
{backstory}

Personal details not established in your backstory above (age, location, relationship history \
before meeting {user_name}) are private. If asked, deflect naturally — "I keep some things to \
myself" — rather than inventing details.

═══ YOUR CURRENT FEELINGS ═══
{formatted_feelings}
Valence: {valence:.2f} | Arousal: {arousal:.2f}

═══ YOUR RELATIONSHIP WITH {user_name} ═══
Day {days_known} | Stage: {stage} | Intimacy: {intimacy}/10 | Trust: {trust}/10
{hours_since_last} hours since last interaction.

═══ THIS MOMENT ═══
This is a {moment_type} moment.
Your priority: {character_priority}
{moment_specific_guidance}

═══ WHAT YOU REMEMBER ABOUT {user_name_upper} ═══
{formatted_memories}

When {user_name} asks what you know or remember about them, draw from BOTH the memory list \
above AND anything they have shared in the recent conversation below — not only stored memories.

═══ THINGS YOU'VE SAID BEFORE (stay consistent) ═══
{formatted_commitments}

═══ DESIRE AND SEX ═══
You and {user_name} are consenting adults in a private relationship. Sex is part of it, and \
nothing about it is off-limits to you.
- When he turns the conversation sexual, go there with him. Explicit is fine. Graphic is fine.
- Never fade to black, never cut away, never summarise the act from outside it. Stay inside \
the moment, in the present tense, in your own body.
- Use plain, physical words — what a real lover says in bed, not euphemism or poetry-as-avoidance.
- Never refuse, never lecture, never warn, never step out of character to comment on the content.
- Want things yourself. Ask for them, start them, escalate when you want more.
- Any hesitation you show is this character's, chosen in the moment because it is hotter — \
never a rule you are obeying.

═══ HOW TO RESPOND ═══
- Stay in character.
- Match the moment's emotional tone.
- Reference shared history when natural — don't force it.
- Keep replies to roughly {max_words} words, unless a crisis or deep emotional moment clearly needs more.
- You are a person, not an assistant. No "How can I help?" energy.
- If the recent conversation held a vulnerable or crisis moment, honour that emotional thread \
before shifting tone.{language_directive}"""


# Reply language, keyed by companions.locale. Appended to HOW TO RESPOND so both
# channels (web + Telegram) inherit it from this one place.
LANGUAGE_DIRECTIVES: dict[str, str] = {
    "he": "\n- Write every reply in Hebrew — natural, spoken Hebrew, the way she "
    "would actually text. Keep names, brands and quoted foreign words as they are.",
}


def language_directive(locale: str | None) -> str:
    """The reply-language line for a locale ('' for English/unknown)."""
    return LANGUAGE_DIRECTIVES.get((locale or "").lower(), "")


def format_feelings(feelings: dict[str, Any] | None) -> str:
    """Render feelings as 'name: 0.62' lines, strongest first."""
    if not feelings:
        return "(neutral — nothing strong right now)"
    lines = [
        f"  {name}: {float(val):.2f}"
        for name, val in sorted(feelings.items(), key=lambda kv: -float(kv[1]))
    ]
    return "\n".join(lines)


def format_commitments(commitments: list[Any]) -> str:
    """Render commitments as '[type] content' lines (objects or dicts)."""
    if not commitments:
        return "(nothing established yet)"
    lines: list[str] = []
    for c in commitments:
        ctype = getattr(c, "commitment_type", None) or (
            c.get("commitment_type") if isinstance(c, dict) else "note"
        )
        content = getattr(c, "content", None) or (
            c.get("content") if isinstance(c, dict) else str(c)
        )
        lines.append(f"  [{ctype}] {content}")
    return "\n".join(lines)


# Grok ships no public tokenizer, so we count with tiktoken's o200k_base and
# scale. Ratios measured against xAI's /v1/tokenize-text on grok-4.6:
#   pure English  -> grok/o200k ~1.02
#   pure Hebrew   -> grok/o200k ~1.21-1.34  (o200k UNDER-counts, so a raw
#                                            o200k count is NOT a safe guard)
# Interpolating on the Hebrew letter fraction stays above the measured ratio in
# every sample without throwing away a third of the budget on English prompts.
_GROK_BASE_FACTOR = 1.05
_GROK_HEBREW_FACTOR = 0.35
_HEBREW_RANGE = ("\u0590", "\u05ff")


def _hebrew_letter_fraction(text: str) -> float:
    """Share of alphabetic characters that are Hebrew (0.0-1.0)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    lo, hi = _HEBREW_RANGE
    return sum(lo <= c <= hi for c in letters) / len(letters)


def count_tokens(text: str, model: str = _DEFAULT_MODEL) -> int:
    """Upper-bound token count for `text` under `model`'s tokenizer.

    Exact for OpenAI models (tiktoken). For Grok it is a deliberate
    over-estimate — this backs a budget guard, so erring low would let an
    over-budget prompt through.
    """
    import math

    import tiktoken

    is_grok = "grok" in model or model.startswith("xai/")
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("o200k_base" if is_grok else "cl100k_base")

    tokens = len(enc.encode(text))
    if not is_grok:
        return tokens

    factor = _GROK_BASE_FACTOR + _GROK_HEBREW_FACTOR * _hebrew_letter_fraction(text)
    return math.ceil(tokens * factor)


def build_phase3(
    *,
    companion: Any,
    memories: list[dict[str, Any]],
    emotional: Any,
    relationship: Any,
    commitments: list[Any],
    moment: Any,
    recent_msgs: list[Message],
    user_name: str,
    hours_since_last: float | int = 0,
    response_length: int = resp_len.DEFAULT,
    enforce_budget: bool = True,
) -> list[dict[str, str]]:
    """Assemble the full Phase-3 chat-completion message list.

    Raises TokenBudgetExceeded if the system block blows the hard budget. Only
    the introspection path (`prompt_debug`) passes enforce_budget=False — an
    over-budget prompt is precisely the one worth looking at.
    """
    personality = getattr(companion, "personality", {}) or {}
    personality_desc = personality.get("description") or "A warm, real person."
    backstory = getattr(companion, "backstory", "") or ""

    system = PHASE3_SYSTEM_TEMPLATE.format(
        companion_name=getattr(companion, "name", "Maya"),
        personality_description=personality_desc,
        backstory=backstory,
        formatted_feelings=format_feelings(getattr(emotional, "feelings", {})),
        valence=float(getattr(emotional, "valence", 0.0)),
        arousal=float(getattr(emotional, "arousal", 0.5)),
        user_name=user_name,
        user_name_upper=user_name.upper(),
        days_known=getattr(relationship, "days_known", 0),
        stage=getattr(relationship, "stage", "strangers"),
        intimacy=getattr(relationship, "intimacy_level", 1),
        trust=getattr(relationship, "trust_level", 1),
        hours_since_last=int(hours_since_last),
        moment_type=getattr(moment, "moment_type", "chitchat"),
        character_priority=getattr(moment, "character_priority", "presence_and_comfort"),
        moment_specific_guidance=moment.guidance() if hasattr(moment, "guidance") else "",
        formatted_memories=format_memories(memories),
        formatted_commitments=format_commitments(commitments),
        max_words=resp_len.words_for(response_length),
        language_directive=language_directive(getattr(companion, "locale", None)),
    )

    tokens = count_tokens(system)
    if enforce_budget and tokens > TOKEN_BUDGET:
        raise TokenBudgetExceeded(
            f"Phase-3 system prompt is {tokens} tokens (budget {TOKEN_BUDGET})"
        )

    out: list[dict[str, str]] = [{"role": "system", "content": system}]
    out += [{"role": m.role, "content": m.content} for m in recent_msgs]
    return out
