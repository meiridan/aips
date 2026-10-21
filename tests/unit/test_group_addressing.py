"""Group chat routing: who a message is for."""

from __future__ import annotations

import uuid

import pytest

from maya.conversation.addressing import TARGET_ALL, Addressable, resolve_addressees

MAYA = uuid.uuid4()
LILA = uuid.uuid4()
MEMBERS = [
    Addressable(MAYA, "primary", ("מאיה", "maya")),
    Addressable(LILA, "lila", ("לילה", "lila")),
]
BOTH = [MAYA, LILA]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("מאיה, מה נשמע?", [MAYA]),
        ("מאיה מה נשמע", [MAYA]),
        ("לילה, מה איתך", [LILA]),
        ("לילה: בואי רגע", [LILA]),
        ("לילה", [LILA]),
        ("@לילה מה קורה", [LILA]),
        ("היי מאיה", [MAYA]),
        ("שלום לילה", [LILA]),
        ("מאיה ולילה, בואו נדבר", BOTH),
        ("לילה ומאיה", [LILA, MAYA]),
        ("Maya what's up", [MAYA]),
        ("LILA: hi", [LILA]),
        ("מָאיָה, שלום", [MAYA]),
        # Not a vocative: no name up front.
        ("מה נשמע בנות", BOTH),
        ("אני אוהב את מאיה", BOTH),
        ("", BOTH),
    ],
)
def test_leading_names_pick_the_addressees(text, expected):
    assert resolve_addressees(text, MEMBERS) == expected


@pytest.mark.parametrize("text", ["לילה טוב", "לילה טוב לשתיכן", "לילה ארוך היה"])
def test_lila_as_the_word_night_is_not_a_vocative(text):
    """ "לילה טוב" is "good night" — routing it to Lila alone would be wrong."""
    assert resolve_addressees(text, MEMBERS) == BOTH


def test_explicit_target_beats_the_text():
    assert resolve_addressees("מאיה, רק את", MEMBERS, target="lila") == [LILA]
    assert resolve_addressees("מאיה, רק את", MEMBERS, target=TARGET_ALL) == BOTH


def test_unknown_target_falls_back_to_the_text():
    assert resolve_addressees("מאיה, היי", MEMBERS, target="nobody") == [MAYA]
