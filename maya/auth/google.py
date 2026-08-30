"""Google sign-in: Authorization Code + PKCE, by hand over `httpx`.

No `google-auth` / `pyjwt` dependency, and none is needed. The usual reason to
pull one in is verifying the signature on an `id_token` that arrived through
the browser. Here the code is exchanged server-to-server over TLS directly with
Google, and the profile is read from Google's userinfo endpoint on that same
channel — there is no third-party-supplied token to verify, so a JWT library
would only be re-deriving what the transport already guarantees.

CSRF is handled by `state`: a random value is stored in a short-lived cookie
and compared on the way back, so a callback the user never initiated is
rejected before any account is touched.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

import httpx

from maya.config import get_settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPE = "openid email profile"
_TIMEOUT = 15.0

# Cookies that carry the flow's state across the redirect to Google. Short-lived
# and HttpOnly; they are meaningless once the callback has run.
STATE_COOKIE = "g_state"
VERIFIER_COOKIE = "g_verifier"
FLOW_COOKIE_MAX_AGE = 600  # 10 minutes to get through Google's consent screen.


class GoogleError(RuntimeError):
    """The flow could not be completed."""


@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str
    email_verified: bool
    name: str | None


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    settings = get_settings()
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    base = settings.public_base_url.rstrip("/") or "http://localhost:8000"
    return f"{base}/auth/google/callback"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_state() -> str:
    return secrets.token_urlsafe(24)


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge_for(verifier: str) -> str:
    """S256 PKCE challenge.

    PKCE binds the callback's code to this browser, so an intercepted code is
    useless without the verifier that never left the server.
    """
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def authorization_url(*, state: str, verifier: str) -> str:
    settings = get_settings()
    params = httpx.QueryParams(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            # Otherwise a signed-in Google user is bounced straight through and
            # can never switch accounts.
            "prompt": "select_account",
        }
    )
    return f"{AUTH_ENDPOINT}?{params}"


async def exchange_code(code: str, verifier: str) -> GoogleProfile:
    """Trade the callback's code for the signed-in user's profile."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        token_response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if token_response.status_code >= 400:
            raise GoogleError(f"token exchange failed ({token_response.status_code})")
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise GoogleError("token exchange returned no access_token")

        profile_response = await client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if profile_response.status_code >= 400:
            raise GoogleError(f"userinfo failed ({profile_response.status_code})")

    claims = profile_response.json()
    subject, email = claims.get("sub"), claims.get("email")
    if not subject or not email:
        raise GoogleError("userinfo returned no subject or email")

    return GoogleProfile(
        subject=str(subject),
        email=str(email),
        # Google reports this per-address; an unverified one must not be
        # allowed to claim an existing password account by email match.
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name"),
    )
