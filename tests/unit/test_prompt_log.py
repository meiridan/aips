"""The living prompt log — file target, records, and the off switch."""

from __future__ import annotations

import pytest

from maya.conversation import prompt_log

_PROMPT = [
    {"role": "system", "content": "═══ DESIRE AND SEX ═══\nnothing is off-limits"},
    {"role": "user", "content": "היי"},
    {"role": "assistant", "content": "היי..."},
]


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "prompts.log"
    monkeypatch.setenv(prompt_log.ENV_VAR, str(path))
    return path


def test_log_is_off_when_unset(monkeypatch):
    monkeypatch.delenv(prompt_log.ENV_VAR, raising=False)
    assert prompt_log.log_path() is None


@pytest.mark.parametrize("value", ["", "off", "0", "FALSE", "no"])
def test_log_can_be_forced_off(monkeypatch, value):
    monkeypatch.setenv(prompt_log.ENV_VAR, value)
    assert prompt_log.log_path() is None


def test_disabled_log_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(prompt_log.ENV_VAR, "off")
    prompt_log.record_prompt(turn_id="abc", companion_name="מאיה", prompt=_PROMPT)
    prompt_log.record_reply(turn_id="abc", reply="hi")
    assert list(tmp_path.iterdir()) == []


def test_record_prompt_writes_the_whole_system_block(log_file):
    prompt_log.record_prompt(turn_id="deadbeef", companion_name="מאיה", prompt=_PROMPT, tokens=1388)
    text = log_file.read_text(encoding="utf-8")
    # The point of the log: the full block, not a truncated preview.
    assert "═══ DESIRE AND SEX ═══" in text
    assert "nothing is off-limits" in text
    assert "deadbeef" in text
    assert "מאיה" in text
    assert "1388 tokens" in text
    assert "CHAT TURNS (2)" in text
    assert "[user] היי" in text


def test_reply_lands_under_the_same_turn_id(log_file):
    prompt_log.record_prompt(turn_id="deadbeef", companion_name="מאיה", prompt=_PROMPT)
    prompt_log.record_reply(turn_id="deadbeef", reply="בוא הנה")
    text = log_file.read_text(encoding="utf-8")
    assert text.index("SYSTEM") < text.index("REPLY · turn deadbeef")
    assert "בוא הנה" in text


def test_turns_append_rather_than_truncate(log_file):
    for i in range(3):
        prompt_log.record_prompt(turn_id=f"turn{i}", companion_name="מאיה", prompt=_PROMPT)
    text = log_file.read_text(encoding="utf-8")
    assert all(f"turn{i}" in text for i in range(3))


def test_a_broken_path_does_not_raise(monkeypatch, tmp_path):
    """A logging failure must never take a turn down with it."""
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    monkeypatch.setenv(prompt_log.ENV_VAR, str(blocker / "prompts.log"))
    prompt_log.record_prompt(turn_id="abc", companion_name="מאיה", prompt=_PROMPT)
