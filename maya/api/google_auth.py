"""The two browser-facing Google OAuth routes.

Kept out of `maya/api/auth.py` because these are redirects, not JSON: they live
outside /api and answer with 302s the browser follows.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from maya.auth import accounts, google, ratelimit, sessions
from maya.db.session import get_sessionmaker
from maya.logging import get_logger

log = get_logger("maya.auth.google")

router = APIRouter(prefix="/auth/google", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _flow_cookie_params() -> dict:
    # Same flags as the session cookie, minus the long lifetime. NOT SameSite=
    # Strict: the callback is a cross-site navigation back from Google, and a
    # Strict cookie would not be sent with it.
    params = sessions.cookie_params()
    params["max_age"] = google.FLOW_COOKIE_MAX_AGE
    return params


@router.get("/start")
async def start(request: Request) -> RedirectResponse:
    """Send the browser to Google's consent screen.

    This URL is reached by clicking a link, so failures redirect back to the
    login screen with an error key rather than answering JSON — a browser
    showing a raw `{"detail": ...}` body is a dead end for the person who
    clicked. The SPA normally hides the button entirely (see /api/catalog), so
    this only catches a stale bundle or a hand-typed URL.
    """
    if not google.is_configured():
        return RedirectResponse("/login?error=google_not_configured", status_code=302)

    state, verifier = google.new_state(), google.new_verifier()
    response = RedirectResponse(
        google.authorization_url(state=state, verifier=verifier), status_code=302
    )
    params = _flow_cookie_params()
    response.set_cookie(google.STATE_COOKIE, state, **params)
    response.set_cookie(google.VERIFIER_COOKIE, verifier, **params)
    return response


@router.get("/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None
) -> RedirectResponse:
    """Complete the flow and sign the user in."""
    if not google.is_configured():
        raise HTTPException(status_code=503, detail="google_not_configured")
    ratelimit.enforce(f"google:{_client_ip(request)}", ratelimit.GOOGLE_CALLBACK)

    expected_state = request.cookies.get(google.STATE_COOKIE)
    verifier = request.cookies.get(google.VERIFIER_COOKIE)

    # The CSRF check. Without it, an attacker could hand someone a callback URL
    # and sign their browser into the attacker's Google account.
    if not code or not state or not expected_state or state != expected_state or not verifier:
        raise HTTPException(status_code=400, detail="invalid_oauth_state")

    try:
        profile = await google.exchange_code(code, verifier)
    except google.GoogleError as exc:
        log.warning("google_exchange_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="google_exchange_failed") from None

    sm = get_sessionmaker()
    user = await accounts.get_by_google_sub(sm, profile.subject)
    if user is None:
        existing = await accounts.get_by_email(sm, profile.email)
        if existing is not None:
            # Link, so signing in with Google reaches the same companion as the
            # password account — but only on an address Google says it verified,
            # or an unverified claim could take over someone else's account.
            if not profile.email_verified:
                raise HTTPException(status_code=400, detail="google_email_unverified")
            await accounts.link_google(sm, existing.id, profile.subject)
            user = existing
        else:
            user = await accounts.create(
                sm,
                email=profile.email,
                google_sub=profile.subject,
                name=profile.name,
                email_verified=profile.email_verified,
            )

    token = await sessions.issue(
        sm,
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    await accounts.note_login(sm, user.id)

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        sessions.COOKIE_NAME,
        token,
        max_age=sessions.max_age_seconds(),
        **sessions.cookie_params(),
    )
    # The flow cookies have done their job; leaving them around is needless.
    response.delete_cookie(google.STATE_COOKIE, path="/")
    response.delete_cookie(google.VERIFIER_COOKIE, path="/")
    log.info("google_login", user_id=str(user.id))
    return response
