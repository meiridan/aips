"""Regression tracking store (§P4.7)."""

from __future__ import annotations

import pytest

from tests.simulator.evaluate import EvaluationScore
from tests.simulator.regression import (
    compare_runs,
    find_regressions,
    insert_eval_run,
    latest_run,
)


def _score(**overrides) -> EvaluationScore:
    base = dict(
        feels_alive=7.0, feels_consistent=7.0, feels_emotionally_intelligent=7.0,
        feels_like_real_relationship=7.0, memory_recall_quality=7.0,
        initiative_quality=0.0, failure_modes=[], standout_moments=[],
    )
    base.update(overrides)
    return EvaluationScore(**base)


@pytest.mark.asyncio
async def test_insert_and_latest(db_sessionmaker):
    await insert_eval_run("lonely_dev", days=2, seed=42, score=_score(feels_alive=6.0),
                          git_sha="aaa", cost_usd=0.01, sessionmaker=db_sessionmaker)
    await insert_eval_run("lonely_dev", days=2, seed=42, score=_score(feels_alive=8.0),
                          git_sha="bbb", cost_usd=0.02, sessionmaker=db_sessionmaker)

    run = await latest_run("lonely_dev", sessionmaker=db_sessionmaker)
    assert run is not None
    assert run.git_sha == "bbb"
    assert run.scores["feels_alive"] == 8.0


@pytest.mark.asyncio
async def test_latest_run_none_when_absent(db_sessionmaker):
    assert await latest_run("nobody", sessionmaker=db_sessionmaker) is None


def test_find_regressions_detects_big_drop():
    baseline = {"feels_alive": 8.0, "feels_consistent": 7.0}
    cand = _score(feels_alive=6.5, feels_consistent=7.2)
    regs = find_regressions(baseline, cand)
    dims = {r["dimension"] for r in regs}
    assert "feels_alive" in dims  # dropped 1.5 > 1.0
    assert "feels_consistent" not in dims  # improved


def test_find_regressions_empty_without_baseline():
    assert find_regressions(None, _score()) == []


@pytest.mark.asyncio
async def test_compare_runs_flags_regression(db_sessionmaker):
    await insert_eval_run("lonely_dev", days=2, seed=42,
                          score=_score(feels_alive=8.0, feels_consistent=8.0),
                          git_sha="base", cost_usd=0.0, sessionmaker=db_sessionmaker)
    await insert_eval_run("lonely_dev", days=2, seed=42,
                          score=_score(feels_alive=6.5, feels_consistent=8.3),
                          git_sha="cand", cost_usd=0.0, sessionmaker=db_sessionmaker)

    rows = await compare_runs("base", "cand", sessionmaker=db_sessionmaker)
    by_dim = {r["persona_dim"]: r for r in rows}
    alive = by_dim["lonely_dev / feels_alive"]
    assert alive["delta"] == pytest.approx(-1.5)
    assert alive["regression"] is True
    cons = by_dim["lonely_dev / feels_consistent"]
    assert cons["regression"] is False
