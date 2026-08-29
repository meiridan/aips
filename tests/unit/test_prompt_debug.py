"""Tests for the prompt introspection path (`maya show-prompt`).

The point of these is drift: `prompt_debug._sources` hand-maps every
PHASE3_SYSTEM_TEMPLATE placeholder to its origin, so it goes stale silently the
moment the template grows a field. `test_source_map_covers_every_template_field`
is the tripwire.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maya.conversation.moment_analyzer import (
    MOMENT_GUIDANCE,
    MomentAnalysis,
    default_moment,
)
from maya.conversation.prompt_builder import TOKEN_BUDGET, TokenBudgetExceeded, build_phase3
from maya.conversation.prompt_debug import (
    Source,
    _sources,
    resolve_moment,
    template_fields,
)


def _fixtures(**overrides):
    base = dict(
        companion=SimpleNamespace(
            name="Maya",
            personality={"description": "openly sexual and uninhibited"},
            backstory="Grew up in Haifa.",
            locale="he",
            response_length=2,
        ),
        user_name="Idan",
        emotional=SimpleNamespace(feelings={"warm": 0.6}, valence=0.4, arousal=0.5),
        relationship=SimpleNamespace(
            days_known=30, stage="committed", intimacy_level=10, trust_level=9
        ),
        memories=[{"text": "likes espresso"}],
        commitments=[],
        moment=default_moment(),
        hours_since=2.0,
        length_level=2,
    )
    base.update(overrides)
    return base


def test_source_map_covers_every_template_field():
    """Every {placeholder} in the template must have a documented origin."""
    mapped = {s.field for s in _sources(**_fixtures())}
    assert mapped == template_fields()


def test_every_source_names_a_real_origin():
    for s in _sources(**_fixtures()):
        assert isinstance(s, Source)
        assert s.origin.strip(), f"{s.field} has no origin"


def test_moment_guidance_source_reports_the_live_guidance():
    """The intimate moment's guidance must be visible in the dump verbatim."""
    intimate = _sources(**_fixtures(moment=MomentAnalysis(moment_type="intimate")))
    row = next(s for s in intimate if s.field == "moment_specific_guidance")
    assert "He wants you" in row.value


def test_language_directive_source_reports_locale():
    he = next(s for s in _sources(**_fixtures()) if s.field == "language_directive")
    assert "Hebrew" in he.value

    companion = _fixtures()["companion"]
    companion.locale = None
    en = next(
        s for s in _sources(**_fixtures(companion=companion)) if s.field == "language_directive"
    )
    assert "none" in en.value


def test_moment_source_note_flags_the_default_moment_gap():
    """The live path builds with default_moment(); the dump must say so."""
    row = next(s for s in _sources(**_fixtures()) if s.field == "moment_type")
    assert "default_moment()" in row.note


class TestResolveMoment:
    def test_default_is_the_live_critical_path(self):
        moment, desc = resolve_moment("default")
        assert moment is not None
        assert moment.moment_type == "chitchat"
        assert "live main call" in desc

    def test_auto_defers_to_the_analyzer(self):
        moment, desc = resolve_moment("auto")
        assert moment is None
        assert "paid" in desc

    def test_forced_moment_carries_its_real_guidance(self):
        moment, desc = resolve_moment("intimate")
        assert moment.moment_type == "intimate"
        assert moment.guidance() == MOMENT_GUIDANCE["intimate"]
        assert "forced" in desc

    def test_unknown_moment_is_rejected_with_the_valid_list(self):
        with pytest.raises(ValueError, match="unknown moment"):
            resolve_moment("horny")


def _build(enforce: bool, backstory: str):
    f = _fixtures()
    f["companion"].backstory = backstory
    return build_phase3(
        companion=f["companion"],
        memories=f["memories"],
        emotional=f["emotional"],
        relationship=f["relationship"],
        commitments=f["commitments"],
        moment=f["moment"],
        recent_msgs=[],
        user_name=f["user_name"],
        hours_since_last=2,
        response_length=2,
        enforce_budget=enforce,
    )


class TestEnforceBudget:
    def test_budget_is_enforced_by_default(self):
        with pytest.raises(TokenBudgetExceeded):
            _build(True, "word " * (TOKEN_BUDGET + 1000))

    def test_introspection_can_see_an_over_budget_prompt(self):
        msgs = _build(False, "word " * (TOKEN_BUDGET + 1000))
        assert msgs[0]["role"] == "system"
        assert "word word" in msgs[0]["content"]
