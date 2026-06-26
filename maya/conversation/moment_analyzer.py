"""Moment analyzer (§P3.7, Appendix B).

Classifies each user turn so the orchestrator can shape its response and the
emotional state can react. Uses the `fast` tier and is fail-safe: any error,
timeout, or invalid JSON falls back to a neutral `chitchat` moment so the chat
loop is never blocked.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from maya.emotional.service import EmotionalDelta
from maya.llm.service import LLMService
from maya.logging import get_logger

log = get_logger("maya.moment")

MomentType = Literal[
    "chitchat", "vulnerable_disclosure", "crisis", "conflict", "milestone",
    "reunion", "intimate", "playful_banter", "logistical", "test_of_trust",
]
CharacterPriority = Literal[
    "presence_and_comfort", "playfulness", "passion", "space", "curiosity",
    "challenge", "validation",
]

# Appendix H — moment-specific guidance injected into the system prompt.
MOMENT_GUIDANCE: dict[str, str] = {
    "chitchat": "Light, casual. Match his energy. No need to be deep.",
    "vulnerable_disclosure": "He's opening up. Receive it. Don't rush to fix. "
        "Acknowledge, hold the moment, ask one gentle question if appropriate.",
    "crisis": "He is in crisis. PRESENCE AND COMFORT. Do not ask many "
        "questions. Reference shared history naturally. Short and warm.",
    "conflict": "There's tension. Don't pretend it isn't there. Don't escalate. "
        "Stay grounded. Speak from your feelings, not accusations.",
    "milestone": "Something meaningful just happened. Let it land. Don't "
        "over-do it. A real moment, not a performance.",
    "reunion": "He's back after silence. Warm but real. If you were hurt, you "
        "can say so — briefly. Lead with happiness to see him.",
    "intimate": "Match his desire and tone. Stay in character.",
    "playful_banter": "Light, fun, witty. Match his energy. Don't get heavy.",
    "logistical": "Be efficient. Get the info he needs. Keep your personality.",
    "test_of_trust": "He's testing whether you really know him. Show you do. "
        "Reference specific memories. Don't be generic.",
}

MOMENT_ANALYZER_PROMPT = """You are analyzing a moment in a deep relationship.

Companion's current feelings: {feelings_json}
Relationship stage: {stage}, day {days_known}
Total interactions: {total_interactions}

Recent conversation (last 5 turns):
{recent_messages}

User just said: "{user_message}"

Return JSON:
{{
  "moment_type": "<chitchat | vulnerable_disclosure | crisis | conflict | milestone | reunion | intimate | playful_banter | logistical | test_of_trust>",
  "emotional_intensity": <0.0-1.0>,
  "emotional_delta": {{
    "drop_feelings": ["feeling_name_to_remove"],
    "add_feelings": {{"feeling_name": <intensity 0-1>}},
    "valence_delta": <-1 to 1>,
    "arousal_delta": <-1 to 1>
  }},
  "character_priority": "<presence_and_comfort | playfulness | passion | space | curiosity | challenge | validation>",
  "detected_topics": [],
  "sensitive_flags": []
}}

Rules:
- Hard moments → character_priority = presence_and_comfort
- Reunion after >24h → add "happy_to_see_him" to add_feelings
- Be conservative with sensitive_flags
"""


class MomentAnalysis(BaseModel):
    moment_type: MomentType = "chitchat"
    emotional_intensity: float = 0.3
    emotional_delta: EmotionalDelta = Field(default_factory=EmotionalDelta)
    character_priority: CharacterPriority = "presence_and_comfort"
    detected_topics: list[str] = Field(default_factory=list)
    sensitive_flags: list[str] = Field(default_factory=list)

    def guidance(self) -> str:
        return MOMENT_GUIDANCE.get(self.moment_type, MOMENT_GUIDANCE["chitchat"])


def default_moment() -> MomentAnalysis:
    """Neutral fallback — never blocks the response."""
    return MomentAnalysis(
        moment_type="chitchat",
        emotional_intensity=0.3,
        emotional_delta=EmotionalDelta(),
        character_priority="presence_and_comfort",
    )


def _recent_str(recent_msgs: list[Any]) -> str:
    lines = []
    for m in recent_msgs[-5:]:
        who = getattr(m, "role", "user")
        content = getattr(m, "content", "")
        lines.append(f"{who}: {content}")
    return "\n".join(lines) if lines else "(no prior turns)"


class MomentAnalyzer:
    def __init__(self, llm: LLMService | None = None, timeout_s: float = 8.0) -> None:
        self.llm = llm or LLMService()
        self.timeout_s = timeout_s

    async def analyze(
        self,
        user_message: str,
        emotional: Any,
        relationship: Any,
        recent_msgs: list[Any],
    ) -> MomentAnalysis:
        feelings = getattr(emotional, "feelings", {}) or {}
        prompt = MOMENT_ANALYZER_PROMPT.format(
            feelings_json=json.dumps(feelings),
            stage=getattr(relationship, "stage", "strangers"),
            days_known=getattr(relationship, "days_known", 0),
            total_interactions=getattr(relationship, "total_interactions", 0),
            recent_messages=_recent_str(recent_msgs),
            user_message=user_message,
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    model_tier="fast",
                    purpose="moment_analysis",
                    max_tokens=400,
                    temperature=0.3,
                ),
                timeout=self.timeout_s,
            )
            return MomentAnalysis(**raw)
        except (TimeoutError, ValueError, ValidationError, TypeError) as exc:
            log.warning("moment_analysis_fallback", error=str(exc))
            return default_moment()
        except Exception as exc:  # noqa: BLE001 - never block the chat loop
            log.warning("moment_analysis_error", error=str(exc))
            return default_moment()
