"""Feeling half-lives + decay math (§P3.4).

Decay model per Decision 1 (lazy-on-read): the math runs only when state is
fetched, computed from hours since `last_updated`. No background worker.
"""

from __future__ import annotations

FEELING_HALF_LIVES: dict[str, float] = {
    "missing_him": 12.0,
    "playful": 2.0,
    "angry": 6.0,
    "hurt": 24.0,
    "in_love": 168.0,  # 1 week
    "excited": 4.0,
    "tender": 8.0,
    "worried": 18.0,
    "happy_to_see_him": 3.0,
    "curious": 6.0,
}
DEFAULT_HALF_LIFE = 12.0


def half_life_for(feeling: str) -> float:
    """Half-life (hours) for a named feeling, falling back to the default."""
    return FEELING_HALF_LIVES.get(feeling, DEFAULT_HALF_LIFE)


def decay_feeling(
    current: float,
    baseline: float,
    hours_elapsed: float,
    half_life: float,
) -> float:
    """Exponentially decay `current` toward `baseline` over `hours_elapsed`.

    After exactly one half-life the gap to baseline halves.
    """
    if half_life <= 0:
        return baseline
    decay_factor = 0.5 ** (hours_elapsed / half_life)
    return baseline + (current - baseline) * decay_factor
