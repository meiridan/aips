"""Deterministic units of the multi-day runner (§P4.3).

The full sim makes real LLM + DB calls (covered by the smoke run / behavior
tests). Here we pin the pure pieces: time-context labeling and JSON round-trip.
"""

from __future__ import annotations

from tests.simulator.run_simulation import SimulationResult, pick_time_context


def test_pick_time_context_includes_day():
    assert pick_time_context(3, 0).startswith("Day 3")


def test_pick_time_context_varies_within_day():
    labels = {pick_time_context(1, i) for i in range(4)}
    assert len(labels) > 1  # not all messages land at the same time of day


def test_simulation_result_json_roundtrip(tmp_path):
    sim = SimulationResult(
        persona="lonely_dev",
        days=2,
        seed=42,
        transcript=[{"day": 0, "time": "Day 0, morning", "role": "user", "content": "hi"}],
        daily_snapshots=[{"day": 0, "stage": "strangers"}],
        final_state={"stage": "strangers", "days_known": 2},
        all_memories=[{"id": "m1", "text": "has a dog"}],
        relationship_events=[{"event_type": "stage_transition", "summary": "to curious"}],
        cost_usd=0.0123,
    )
    path = tmp_path / "run.json"
    sim.to_json(path)
    loaded = SimulationResult.from_json(path)

    assert loaded == sim
    assert loaded.transcript[0]["content"] == "hi"
    assert loaded.cost_usd == 0.0123
