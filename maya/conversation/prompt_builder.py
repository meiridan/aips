"""Prompt builder. Spec §P2.3.

Phase 2 prompt is intentionally minimal — Phase 4 makes it fancy.
Memory format includes importance score so Maya can weigh what to use.
"""

from __future__ import annotations

from typing import Any

from maya.db.models import Message

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

═══ HOW TO RESPOND ═══
- Stay in character.
- Match the moment's emotional tone.
- Reference shared history when natural — don't force it.
- Conversational length unless emotionally warranted.
- You are a person, not an assistant. No "How can I help?" energy.
- If the recent conversation held a vulnerable or crisis moment, honour that emotional thread \
before shifting tone. Do not pivot straight to playfulness or intimacy without a brief \
acknowledgment."""


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


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Approximate token count via tiktoken (OpenAI tokenizer).

    For Grok the count is approximate but a safe upper-bound guard.
    """
    import tiktoken

    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


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
) -> list[dict[str, str]]:
    """Assemble the full Phase-3 chat-completion message list.

    Raises TokenBudgetExceeded if the system block blows the hard budget.
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
    )

    tokens = count_tokens(system)
    if tokens > TOKEN_BUDGET:
        raise TokenBudgetExceeded(
            f"Phase-3 system prompt is {tokens} tokens (budget {TOKEN_BUDGET})"
        )

    out: list[dict[str, str]] = [{"role": "system", "content": system}]
    out += [{"role": m.role, "content": m.content} for m in recent_msgs]
    return out
