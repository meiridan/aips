"""Password hashing on stdlib scrypt.

scrypt is a memory-hard KDF in `hashlib`, so this needs no dependency. The
stored format is versioned — ``scrypt$n$r$p$salt$hash``, both fields base64 —
so a future move to argon2 can read old hashes and re-hash on next login
without a data migration.
"""

from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import scrypt

# ~92 ms and 32 MiB per hash on a laptop. Deliberately slow: this is the
# backstop behind the login rate limiter, so it must stay expensive to guess.
_N = 2**15
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
# 128 * N * r is exactly 32 MiB, and hashlib's default (maxmem=0) means a
# 32 MiB *ceiling* in OpenSSL — which this hits, raising
# "memory limit exceeded". Ask for headroom explicitly.
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200  # bcrypt-style truncation bugs don't apply, but an
# unbounded password is an easy way to make the server do 32 MiB of work per byte.


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )


def hash_password(password: str) -> str:
    """Return the storable ``scrypt$...`` string for a plaintext password."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check of a plaintext against a stored hash.

    A missing hash (Google-only account) is False, never an error — callers
    treat "no password set" the same as "wrong password" so the response can't
    distinguish the two.
    """
    if not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        # Read the parameters back from the record rather than assuming the
        # current constants, so hashes written before a parameter bump still
        # verify.
        actual = _derive(password, salt, n=int(n_s), r=int(r_s), p=int(p_s))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A real hash of an unguessable string. Verifying against this when the email
# is unknown makes the failure path cost the same ~92 ms as a wrong password,
# so response timing doesn't reveal whether an account exists.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def waste_time_like_a_verify() -> None:
    """Burn one hash's worth of work for a login attempt on an unknown email."""
    verify_password("timing-equalizer", _DUMMY_HASH)


def password_problem(password: str) -> str | None:
    """Return a UI string key describing why a password is unacceptable.

    Mirrors the frontend's `validatePassword`; the server repeats the check
    because client-side validation is a convenience, never a control.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return "password_too_short"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "password_too_long"
    return None
