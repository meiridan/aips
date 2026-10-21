"""The group room's UI settings: defaults and client-patch validation."""

from __future__ import annotations

from maya.conversation.group_settings import GroupSettings


def test_defaults_are_short_and_moderated():
    assert GroupSettings.from_dict(None).as_dict() == {
        "response_length": 1,
        "talk_mode": "moderated",
    }


def test_apply_takes_the_valid_keys_and_reports_a_change():
    settings = GroupSettings()
    assert settings.apply({"type": "settings", "response_length": 3, "talk_mode": "free"})
    assert settings.as_dict() == {"response_length": 3, "talk_mode": "free"}
    assert settings.free
    assert not settings.apply({"response_length": 3})


def test_apply_ignores_junk():
    settings = GroupSettings()
    assert not settings.apply({"response_length": 9, "talk_mode": "chaos"})
    assert not settings.apply({"response_length": True, "talk_mode": None})
    assert settings.as_dict() == {"response_length": 1, "talk_mode": "moderated"}


def test_stored_values_are_normalized_on_load():
    assert GroupSettings.from_dict({"response_length": "2", "talk_mode": "free"}) == GroupSettings(
        2, "free"
    )
