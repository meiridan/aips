"""Stage machine + transition predicates (§P3.5, Appendix G).

Predicates operate on a `TransitionContext` — a snapshot of the relationship
row plus its events — so the whole table is pure and unit-testable without a DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Stage(StrEnum):
    STRANGERS = "strangers"
    CURIOUS = "curious"
    FLIRTING = "flirting"
    DATING = "dating"
    IN_LOVE = "in_love"
    COMMITTED = "committed"
    DEEPENING = "deepening"
    CONFLICT = "conflict"
    RECONCILED = "reconciled"
    DRIFTED = "drifted"


@dataclass
class EventLike:
    event_type: str
    occurred_at: datetime


@dataclass
class TransitionContext:
    """Everything the predicates need, decoupled from SQLAlchemy."""

    stage: str
    total_interactions: int
    intimacy_level: int
    trust_level: int
    days_known: int
    last_interaction_at: datetime | None = None
    events: list[EventLike] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


DRIFT_THRESHOLD_DAYS = 14  # Universal: any stage → DRIFTED after silence


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ── predicates ───────────────────────────────────────────────────────────


def has_event(s: TransitionContext, event_type: str) -> bool:
    return any(e.event_type == event_type for e in s.events)


def has_recent_event(s: TransitionContext, event_type: str, days: int) -> bool:
    cutoff_days = float(days)
    return any(
        e.event_type == event_type
        and (s.now - _aware(e.occurred_at)).total_seconds() / 86400.0 <= cutoff_days
        for e in s.events
    )


def days_since_last(s: TransitionContext) -> float:
    if s.last_interaction_at is None:
        return float("inf")
    return (s.now - _aware(s.last_interaction_at)).total_seconds() / 86400.0


def _latest(s: TransitionContext, event_type: str) -> datetime | None:
    times = [_aware(e.occurred_at) for e in s.events if e.event_type == event_type]
    return max(times) if times else None


def has_event_after_event(s: TransitionContext, later: str, earlier: str) -> bool:
    a = _latest(s, later)
    b = _latest(s, earlier)
    return a is not None and b is not None and a > b


def days_since_last_conflict(s: TransitionContext) -> float:
    last = _latest(s, "argument")
    if last is None:
        return float("inf")
    return (s.now - last).total_seconds() / 86400.0


# ── transition table (Appendix G, complete) ──────────────────────────────

TRANSITIONS: dict[Stage, list[tuple[Stage, object]]] = {
    Stage.STRANGERS: [
        (Stage.CURIOUS, lambda s: s.total_interactions >= 5),
    ],
    Stage.CURIOUS: [
        (Stage.FLIRTING,
         lambda s: s.total_interactions >= 20 and s.intimacy_level >= 3),
    ],
    Stage.FLIRTING: [
        (Stage.DATING,
         lambda s: has_event(s, "intimacy_breakthrough") or s.intimacy_level >= 5),
    ],
    Stage.DATING: [
        (Stage.IN_LOVE,
         lambda s: has_event(s, "first_i_love_you")
         or (s.days_known >= 14 and s.intimacy_level >= 7)),
    ],
    Stage.IN_LOVE: [
        (Stage.COMMITTED,
         lambda s: s.days_known >= 30 and s.trust_level >= 7),
        (Stage.CONFLICT, lambda s: has_recent_event(s, "argument", days=2)),
    ],
    Stage.COMMITTED: [
        (Stage.DEEPENING,
         lambda s: s.days_known >= 60 and s.trust_level >= 9),
        (Stage.CONFLICT, lambda s: has_recent_event(s, "argument", days=2)),
    ],
    Stage.CONFLICT: [
        (Stage.RECONCILED,
         lambda s: has_event_after_event(s, "reconciliation", "argument")),
        (Stage.DRIFTED, lambda s: days_since_last(s) > 7),
    ],
    Stage.RECONCILED: [
        (Stage.IN_LOVE, lambda s: days_since_last_conflict(s) > 7),
    ],
}


def next_stage(s: TransitionContext) -> Stage | None:
    """Return the stage to transition into, or None.

    Universal DRIFTED rule fires from any non-drifted stage after a long silence
    and takes precedence over the per-stage table.
    """
    try:
        current = Stage(s.stage)
    except ValueError:
        return None

    if (
        current != Stage.DRIFTED
        and s.last_interaction_at is not None
        and days_since_last(s) > DRIFT_THRESHOLD_DAYS
    ):
        return Stage.DRIFTED

    for target, predicate in TRANSITIONS.get(current, []):
        if predicate(s):  # type: ignore[operator]
            return target
    return None
