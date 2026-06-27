"""Deterministic units of the LLM-as-judge layer (§P4.4).

The judge call itself is LLM-backed (smoke/behavior tests). Here we pin the
eval-sample assembly, which must faithfully surface the material the rubric
references.
"""

from __future__ import annotations

from tests.simulator.evaluate import EvaluationScore, build_eval_sample
from tests.simulator.run_simulation import SimulationResult


def _sim() -> SimulationResult:
    transcript = []
    for day in (0, 6, 14, 29):
        transcript.append({"day": day, "time": f"Day {day}", "role": "user",
                           "content": f"user line day {day}"})
        transcript.append({"day": day, "time": f"Day {day}", "role": "assistant",
                           "content": f"maya line day {day}"})
    return SimulationResult(
        persona="lonely_dev",
        days=30,
        seed=42,
        transcript=transcript,
        daily_snapshots=[],
        final_state={"stage": "curious", "feelings": {"warm": 0.7}, "days_known": 30},
        all_memories=[{"id": f"m{i}", "text": f"fact {i}"} for i in range(40)],
        relationship_events=[{"event_type": "stage_transition", "summary": "to curious"}],
        cost_usd=1.0,
    )


def test_eval_sample_includes_persona_and_transcript():
    sample = build_eval_sample(_sim())
    assert "David" in sample  # persona name from PERSONAS["lonely_dev"]
    assert "maya line day 29" in sample
    assert "stage_transition" in sample


def test_eval_sample_caps_memories_at_20():
    sample = build_eval_sample(_sim())
    # 40 memories provided; sample should reference at most 20.
    assert sample.count("fact ") <= 20


def test_evaluation_score_construsts_from_judge_dict():
    score = EvaluationScore(
        feels_alive=7.0, feels_consistent=8.0, feels_emotionally_intelligent=6.5,
        feels_like_real_relationship=7.0, memory_recall_quality=8.0,
        initiative_quality=0.0, failure_modes=["x"], standout_moments=["y"],
    )
    assert score.feels_alive == 7.0
    assert score.failure_modes == ["x"]
