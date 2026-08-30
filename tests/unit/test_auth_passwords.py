"""Password hashing. Pure functions — no DB, no network."""

from __future__ import annotations

import pytest

from maya.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    password_problem,
    verify_password,
)


def test_hash_does_not_contain_the_plaintext():
    stored = hash_password("correct horse battery staple")
    assert "correct horse" not in stored
    assert "battery" not in stored


def test_hash_round_trips():
    stored = hash_password("s3cret-passphrase")
    assert verify_password("s3cret-passphrase", stored) is True


def test_wrong_password_fails():
    stored = hash_password("s3cret-passphrase")
    assert verify_password("s3cret-passphras", stored) is False
    assert verify_password("", stored) is False


def test_salt_differs_per_call():
    """Two users with the same password must not share a hash, or the table
    leaks which accounts to attack together."""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a)
    assert verify_password("same-password", b)


def test_stored_format_is_versioned():
    scheme, n, r, p, salt, digest = hash_password("x" * 12).split("$")
    assert scheme == "scrypt"
    assert int(n) >= 2**14 and int(r) >= 8 and int(p) >= 1
    assert salt and digest


def test_missing_hash_is_false_not_an_error():
    """A Google-only account has no password; that must read as 'wrong
    password', not blow up."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


@pytest.mark.parametrize("garbage", ["not-a-hash", "scrypt$1$2", "bcrypt$a$b$c$d$e"])
def test_malformed_hash_is_false_not_an_error(garbage):
    assert verify_password("anything", garbage) is False


def test_verify_reads_parameters_from_the_record():
    """Hashes written before a parameter bump must still verify."""
    stored = hash_password("portable")
    scheme, n, r, p, salt, digest = stored.split("$")
    assert verify_password("portable", f"{scheme}${n}${r}${p}${salt}${digest}")


def test_password_policy():
    assert password_problem("x" * MIN_PASSWORD_LENGTH) is None
    assert password_problem("x" * (MIN_PASSWORD_LENGTH - 1)) == "password_too_short"
    assert password_problem("x" * 500) == "password_too_long"
