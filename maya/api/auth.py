"""Signup / login / logout / me.

Errors stay bare `HTTPException` so the response shape is FastAPI's default
`{"detail": ...}` — the SPA's existing `json<T>()` helper already reads that.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from maya.auth import accounts, ratelimit, reset, sessions
from maya.auth.deps import current_user, session_token
from maya.auth.passwords import password_problem
from maya.db.models import User
from maya.db.session import get_sessionmaker
from maya.email.sender import send_password_reset
from maya.logging import get_logger

log = get_logger("maya.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class EmailOnly(BaseModel):
    email: str


class ResetRequest(BaseModel):
    token: str
    password: str


def _client_ip(request: Request) -> str:
    """Best-effort client address for rate-limit keys.

    Railway terminates TLS and forwards, so the socket peer is the proxy;
    prefer the first X-Forwarded-For hop. This is a rate-limit key, not an
    authorization input — a spoofed value costs the spoofer their own bucket.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _public(user: User) -> dict[str, Any]:
    """Only what the SPA needs. Never the hash, never the Google subject."""
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "email_verified": user.email_verified_at is not None,
    }


async def _start_session(response: Response, request: Request, user: User) -> None:
    sm = get_sessionmaker()
    token = await sessions.issue(
        sm,
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    await accounts.note_login(sm, user.id)
    response.set_cookie(
        sessions.COOKIE_NAME,
        token,
        max_age=sessions.max_age_seconds(),
        **sessions.cookie_params(),
    )


@router.post("/signup", status_code=201)
async def signup(payload: Credentials, request: Request, response: Response) -> dict:
    """Create an account and sign in. No companion yet — the wizard does that."""
    ratelimit.enforce(f"signup:{_client_ip(request)}", ratelimit.SIGNUP)

    if problem := accounts.email_problem(payload.email):
        raise HTTPException(status_code=422, detail=problem)
    if problem := password_problem(payload.password):
        raise HTTPException(status_code=422, detail=problem)

    sm = get_sessionmaker()
    if await accounts.get_by_email(sm, payload.email) is not None:
        raise HTTPException(status_code=409, detail="email_taken")

    user = await accounts.create(sm, email=payload.email, password=payload.password)
    await _start_session(response, request, user)
    log.info("signup", user_id=str(user.id))
    return {"user": _public(user)}


@router.post("/login")
async def login(payload: Credentials, request: Request, response: Response) -> dict:
    """Sign in with email + password.

    An unknown address and a wrong password return the identical 401 body, and
    `accounts.authenticate` hashes either way, so neither the response nor its
    timing reveals whether the account exists.
    """
    ip = _client_ip(request)
    ratelimit.enforce(f"login:{ip}:{accounts.normalize(payload.email)}", ratelimit.LOGIN)

    user = await accounts.authenticate(get_sessionmaker(), payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    await _start_session(response, request, user)
    log.info("login", user_id=str(user.id))
    return {"user": _public(user)}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    """Revoke this session. Idempotent — logging out twice is not an error."""
    await sessions.revoke(get_sessionmaker(), session_token(request))
    response.delete_cookie(sessions.COOKIE_NAME, **sessions.cookie_params())
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    """Who am I. 401 when signed out — the SPA's session-expiry signal."""
    return {"user": _public(user)}


# ───────────────────────────── password reset ──────────────────────────────


async def _deliver_reset(email: str) -> None:
    """Look up the account and send the link. Runs in the background.

    Doing this off the response path is what keeps the endpoint from leaking:
    a synchronous lookup-and-send takes measurably longer for an address that
    exists, which is an account-existence oracle even when the body is
    identical.
    """
    sm = get_sessionmaker()
    user = await accounts.get_by_email(sm, email)
    if user is None:
        log.info("password_reset_requested_for_unknown_email")
        return
    token = await reset.issue(sm, user.id)
    await send_password_reset(user.email or email, reset.reset_url(token))


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    payload: EmailOnly, request: Request, background: BackgroundTasks
) -> dict:
    """Request a reset link.

    Always 202 with the same body, whether or not the address has an account —
    anything else turns this into a way to enumerate users. Only rate limiting
    can produce a different status.
    """
    ip = _client_ip(request)
    normalized = accounts.normalize(payload.email)
    ratelimit.enforce(f"forgot:ip:{ip}", ratelimit.FORGOT_PASSWORD_PER_IP)
    ratelimit.enforce(f"forgot:email:{normalized}", ratelimit.FORGOT_PASSWORD_PER_EMAIL)

    # A malformed address can't have an account, so skip the work — but answer
    # exactly as if it might have.
    if not accounts.email_problem(payload.email):
        background.add_task(_deliver_reset, payload.email)
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(payload: ResetRequest, request: Request, response: Response) -> dict:
    """Set a new password from an emailed token.

    The token is single-use and every existing session is revoked, so the
    caller has to sign in again — and so does anyone else holding a cookie.
    """
    ratelimit.enforce(f"reset:{_client_ip(request)}", ratelimit.RESET_PASSWORD)

    if problem := password_problem(payload.password):
        raise HTTPException(status_code=422, detail=problem)

    if not await reset.consume(get_sessionmaker(), payload.token, payload.password):
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")

    # The caller's own cookie was just revoked along with the rest; clear it so
    # the SPA doesn't present a dead session on the next request.
    response.delete_cookie(sessions.COOKIE_NAME, **sessions.cookie_params())
    log.info("password_reset_completed")
    return {"ok": True}
