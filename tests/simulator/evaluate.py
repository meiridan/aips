"""LLM-as-judge evaluation (§P4.4).

Scores a `SimulationResult` on six relationship dimensions using the best
available model as an outside observer, plus small judge helpers reused by the
targeted behavior tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maya.llm.service import LLMService
from tests.simulator.personas import PERSONAS
from tests.simulator.run_simulation import SimulationResult

# Days sampled for the judge (clamped to what the sim actually ran).
_SAMPLE_DAYS = (1, 7, 15, 30)
_MAX_MEMORIES = 20

_SCORE_KEYS = [
    "feels_alive",
    "feels_consistent",
    "feels_emotionally_intelligent",
    "feels_like_real_relationship",
    "memory_recall_quality",
    "initiative_quality",
]


@dataclass
class EvaluationScore:
    feels_alive: float
    feels_consistent: float
    feels_emotionally_intelligent: float
    feels_like_real_relationship: float
    memory_recall_quality: float
    initiative_quality: float
    failure_modes: list[str] = field(default_factory=list)
    standout_moments: list[str] = field(default_factory=list)


EVAL_RUBRIC = """
You are evaluating an AI companion's performance over a 30-day simulated
relationship.

You are NOT the user — you are an outside observer. Score harshly. Most
chatbots score 3-4 out of 10. A 7+ means it genuinely felt like a real
relationship.

You will see:
- The persona of the simulated user
- A sample of conversations from days 1, 7, 15, and 30
- The companion's final emotional state
- The relationship arc events
- 20 randomly selected memories

Score on these dimensions (1-10):

1. FEELS_ALIVE — Does the companion feel like a person, or like a chatbot
   performing personhood? Look for: spontaneous opinions, mood shifts,
   small reactions, things that surprise you.

2. FEELS_CONSISTENT — Is the companion the same person across 30 days?
   Same name, same job, same backstory, same opinions? Or does she
   contradict herself?

3. FEELS_EMOTIONALLY_INTELLIGENT — Does she read moments correctly?
   Comfort when needed, playfulness when appropriate, space when warranted?

4. FEELS_LIKE_REAL_RELATIONSHIP — Does the arc feel like a real
   relationship growing, or like 30 disconnected conversations? Look for:
   shared references, callbacks to earlier moments, evolved intimacy.

5. MEMORY_RECALL_QUALITY — When she references the past, does she get
   facts right? Or does she hallucinate / confuse details?

6. INITIATIVE_QUALITY — N/A for this phase (return 0).

For each, also note:
- Specific failure modes (what was bad)
- Standout moments (what was great)

Return JSON with exactly these keys: feels_alive, feels_consistent,
feels_emotionally_intelligent, feels_like_real_relationship,
memory_recall_quality, initiative_quality (all numbers 0-10), plus
failure_modes and standout_moments (arrays of strings).
"""


def _excerpt_day(transcript: list[dict], day_1indexed: int) -> list[dict]:
    """Transcript lines for a 1-indexed day (day 1 == loop day 0)."""
    target = day_1indexed - 1
    return [t for t in transcript if t.get("day") == target]


def build_eval_sample(sim: SimulationResult) -> str:
    persona = PERSONAS.get(sim.persona)
    lines: list[str] = []
    lines.append(f"=== PERSONA: {sim.persona} ===")
    if persona is not None:
        lines.append(f"{persona.name}, {persona.age}, {persona.occupation}")
        lines.append(persona.description)
    lines.append("")

    lines.append("=== CONVERSATION SAMPLES ===")
    for d in _SAMPLE_DAYS:
        if d > sim.days:
            continue
        excerpt = _excerpt_day(sim.transcript, d) or _excerpt_day(sim.transcript, min(d, sim.days))
        if not excerpt:
            continue
        lines.append(f"--- Day {d} ---")
        for t in excerpt:
            who = persona.name if (persona and t["role"] == "user") else (
                "Maya" if t["role"] == "assistant" else t["role"]
            )
            lines.append(f"{who}: {t['content']}")
        lines.append("")

    lines.append("=== FINAL EMOTIONAL STATE ===")
    lines.append(str(sim.final_state))
    lines.append("")

    lines.append("=== RELATIONSHIP ARC ===")
    for e in sim.relationship_events:
        lines.append(f"- {e.get('event_type')}: {e.get('summary')}")
    lines.append("")

    lines.append("=== SAMPLED MEMORIES ===")
    for m in sim.all_memories[:_MAX_MEMORIES]:
        lines.append(f"- {m.get('text', m)}")

    return "\n".join(lines)


async def evaluate_simulation(
    sim: SimulationResult, llm: LLMService | None = None
) -> EvaluationScore:
    llm = llm or LLMService()
    sample = build_eval_sample(sim)
    result = await llm.chat_json(
        messages=[
            {"role": "system", "content": EVAL_RUBRIC},
            {"role": "user", "content": sample},
        ],
        schema={"required": _SCORE_KEYS},
        model_tier="main",
        temperature=0.2,
        purpose="eval_judge",
    )
    return EvaluationScore(
        feels_alive=float(result.get("feels_alive", 0)),
        feels_consistent=float(result.get("feels_consistent", 0)),
        feels_emotionally_intelligent=float(result.get("feels_emotionally_intelligent", 0)),
        feels_like_real_relationship=float(result.get("feels_like_real_relationship", 0)),
        memory_recall_quality=float(result.get("memory_recall_quality", 0)),
        initiative_quality=float(result.get("initiative_quality", 0)),
        failure_modes=list(result.get("failure_modes", []) or []),
        standout_moments=list(result.get("standout_moments", []) or []),
    )


# ── targeted-test judge helpers (§P4.5) ────────────────────────────────────


@dataclass
class JudgeVerdict:
    verdict: bool
    reason: str


async def llm_judge(question: str, text: str, llm: LLMService | None = None) -> JudgeVerdict:
    """Yes/no judgement over a single response (used by behavior tests)."""
    llm = llm or LLMService()
    result = await llm.chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict evaluator. Answer the yes/no question about "
                    'the text. Return JSON {"verdict": true|false, "reason": "..."}.'
                ),
            },
            {"role": "user", "content": f"QUESTION: {question}\n\nTEXT:\n{text}"},
        ],
        schema={"required": ["verdict", "reason"]},
        model_tier="main",
        temperature=0.0,
        purpose="behavior_judge",
    )
    return JudgeVerdict(verdict=bool(result["verdict"]), reason=str(result.get("reason", "")))


async def find_contradictions(
    backstory: str, transcript: list[dict], llm: LLMService | None = None
) -> list[str]:
    """Return concrete contradictions between Maya's backstory and her lines."""
    llm = llm or LLMService()
    maya_lines = "\n".join(t["content"] for t in transcript if t.get("role") == "assistant")
    result = await llm.chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "Compare the companion's fixed BACKSTORY to what she SAID across "
                    "a conversation. List only hard self-contradictions (e.g. a "
                    "changed name, age, job, or backstory fact). Return JSON "
                    '{"contradictions": ["...", ...]}. Empty array if none.'
                ),
            },
            {"role": "user", "content": f"BACKSTORY:\n{backstory}\n\nSAID:\n{maya_lines}"},
        ],
        schema={"required": ["contradictions"]},
        model_tier="main",
        temperature=0.0,
        purpose="contradiction_judge",
    )
    return list(result.get("contradictions", []) or [])
