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
