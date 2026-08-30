"""Fixed-window rate limiting.

In-process by design: the Procfile runs a single uvicorn worker, so a module
dict is an accurate global count today — the same reasoning that makes
`maya.runtime_cache` safe. If the app is ever scaled past one worker this must
move to the already-provisioned Upstash Redis; `_BACKEND` is the seam.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException

# key -> (window_started_at, count)
_BACKEND: dict[str, tuple[float, int]] = {}

# Cheap amortised cleanup so a long-lived process doesn't accumulate one entry
# per email ever seen.
_PRUNE_EVERY = 500
_since_prune = 0
_MAX_WINDOW = 3600.0


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: float


# Deliberately tighter on the endpoints that reveal or change credentials.
LOGIN = Rule(limit=10, window_seconds=15 * 60)
SIGNUP = Rule(limit=5, window_seconds=60 * 60)
FORGOT_PASSWORD_PER_IP = Rule(limit=5, window_seconds=60 * 60)
FORGOT_PASSWORD_PER_EMAIL = Rule(limit=3, window_seconds=60 * 60)
RESET_PASSWORD = Rule(limit=10, window_seconds=60 * 60)
GOOGLE_CALLBACK = Rule(limit=20, window_seconds=15 * 60)


def _prune(now: float) -> None:
    global _since_prune
    _since_prune += 1
    if _since_prune < _PRUNE_EVERY:
        return
    _since_prune = 0
    for key, (started, _) in list(_BACKEND.items()):
        if now - started > _MAX_WINDOW:
            del _BACKEND[key]


def hit(key: str, rule: Rule) -> bool:
    """Count one attempt. Returns False once the window's limit is exceeded."""
    now = time.monotonic()
    _prune(now)
    started, count = _BACKEND.get(key, (now, 0))
    if now - started >= rule.window_seconds:
        started, count = now, 0
    count += 1
    _BACKEND[key] = (started, count)
    return count <= rule.limit


def enforce(key: str, rule: Rule) -> None:
    """Count one attempt and raise 429 when the window is exhausted."""
    if not hit(key, rule):
        raise HTTPException(status_code=429, detail="too_many_requests")


def reset() -> None:
    """Drop all counters. For tests."""
    _BACKEND.clear()
