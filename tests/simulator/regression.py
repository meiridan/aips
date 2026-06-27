"""Regression tracking (§P4.7).

Persists each judged run to `eval_runs` (keyed by git SHA) and diffs two SHAs
so score drops surface as regressions.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict

from sqlalchemy import select

from maya.db.models import EvalRun
from maya.db.session import get_sessionmaker
from tests.simulator.evaluate import _SCORE_KEYS, EvaluationScore

# A candidate dimension dropping more than this vs the base is a regression.
REGRESSION_THRESHOLD = 1.0


def current_git_sha() -> str:
    """Current HEAD SHA, or 'unknown' outside a git checkout."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _scores_dict(score: EvaluationScore) -> dict:
    d = asdict(score)
    return {k: d[k] for k in _SCORE_KEYS}


async def insert_eval_run(
    persona: str,
    days: int,
    seed: int,
    score: EvaluationScore,
    git_sha: str | None = None,
    transcript_path: str | None = None,
    cost_usd: float | None = None,
    sessionmaker=None,
) -> EvalRun:
    sm = sessionmaker or get_sessionmaker()
    async with sm() as session:
        run = EvalRun(
            git_sha=git_sha if git_sha is not None else current_git_sha(),
            persona=persona,
            days=days,
            seed=seed,
            scores=_scores_dict(score),
            failure_modes=list(score.failure_modes),
            standout_moments=list(score.standout_moments),
            transcript_path=transcript_path,
            cost_usd=cost_usd,
        )
        session.add(run)
        await session.commit()
        session.expunge(run)
        return run


def find_regressions(
    baseline_scores: dict | None, candidate: EvaluationScore
) -> list[dict]:
    """Dimensions where `candidate` dropped more than the threshold vs a
    baseline score dict. Empty when there's no baseline to compare against."""
    if not baseline_scores:
        return []
    cand = _scores_dict(candidate)
    regs: list[dict] = []
    for dim in _SCORE_KEYS:
        if dim not in baseline_scores:
            continue
        delta = float(cand[dim]) - float(baseline_scores[dim])
        if delta < -REGRESSION_THRESHOLD:
            regs.append({"dimension": dim, "delta": delta,
                         "base": float(baseline_scores[dim]), "candidate": float(cand[dim])})
    return regs


async def latest_run(persona: str, sessionmaker=None) -> EvalRun | None:
    sm = sessionmaker or get_sessionmaker()
    async with sm() as session:
        run = (
            await session.scalars(
                select(EvalRun)
                .where(EvalRun.persona == persona)
                .order_by(EvalRun.created_at.desc())
                .limit(1)
            )
        ).first()
        if run is not None:
            session.expunge(run)
        return run


async def _runs_for_sha(sha: str, sessionmaker) -> dict[str, EvalRun]:
    async with sessionmaker() as session:
        rows = (
            await session.scalars(
                select(EvalRun).where(EvalRun.git_sha == sha).order_by(EvalRun.created_at)
            )
        ).all()
        # Latest run wins per persona.
        out: dict[str, EvalRun] = {}
        for r in rows:
            session.expunge(r)
            out[r.persona] = r
        return out


async def compare_runs(base_sha: str, candidate_sha: str, sessionmaker=None) -> list[dict]:
    """Per-(persona, dimension) diff between two SHAs. Each row carries the
    base/candidate score, delta, and a regression flag."""
    sm = sessionmaker or get_sessionmaker()
    base = await _runs_for_sha(base_sha, sm)
    cand = await _runs_for_sha(candidate_sha, sm)

    rows: list[dict] = []
    for persona in sorted(set(base) & set(cand)):
        for dim in _SCORE_KEYS:
            b = float(base[persona].scores.get(dim, 0))
            c = float(cand[persona].scores.get(dim, 0))
            delta = c - b
            rows.append({
                "persona_dim": f"{persona} / {dim}",
                "persona": persona,
                "dimension": dim,
                "base": b,
                "candidate": c,
                "delta": delta,
                "regression": delta < -REGRESSION_THRESHOLD,
            })
    return rows
