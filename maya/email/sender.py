"""Transactional email over Resend's HTTP API.

Uses the `httpx` already in the dependency list rather than an SDK — sending is
one POST. When `RESEND_API_KEY` is unset the message is logged instead of sent,
so local dev and the tests exercise the whole reset flow without an account or
a network call.
"""

from __future__ import annotations

import httpx

from maya.config import get_settings
from maya.logging import get_logger

log = get_logger("maya.email")

_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT = 15.0


def _reset_subject() -> str:
    return "איפוס הסיסמה שלך במאיה"


def _reset_body(url: str) -> str:
    """Hebrew, RTL, with the raw URL visible.

    Some mail clients strip or rewrite links, so the address is also printed as
    text — otherwise a stripped anchor leaves the reader with no way through.
    """
    return f"""<!doctype html>
<html lang="he" dir="rtl">
  <body style="font-family:sans-serif;background:#0a0a0f;color:#f2eef5;padding:32px">
    <h2 style="color:#e0338a;margin:0 0 16px">איפוס סיסמה</h2>
    <p style="line-height:1.7;margin:0 0 20px">
      התקבלה בקשה לאיפוס הסיסמה שלך. הקישור תקף לשעה אחת וניתן לשימוש פעם אחת בלבד.
    </p>
    <p style="margin:0 0 24px">
      <a href="{url}"
         style="background:#e0338a;color:#fff;text-decoration:none;
                padding:12px 24px;border-radius:10px;display:inline-block">
        בחירת סיסמה חדשה
      </a>
    </p>
    <p style="color:#8b8494;font-size:13px;line-height:1.7;margin:0">
      אם לא ביקשת לאפס סיסמה, אפשר להתעלם מההודעה — הסיסמה הנוכחית תישאר בתוקף.
    </p>
    <p style="color:#8b8494;font-size:12px;direction:ltr;text-align:left;
              word-break:break-all;margin:16px 0 0">{url}</p>
  </body>
</html>"""


async def send_password_reset(to: str, url: str) -> bool:
    """Send the reset link. Returns whether it was actually handed to Resend.

    Never raises: the caller answers 202 whether or not the address exists, so
    a delivery failure must not change the response and reveal that it did.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        # The link still has to be reachable in dev, so log it. Safe because
        # this branch only runs when no provider is configured at all.
        log.warning("password_reset_email_not_sent", reason="no_resend_api_key", url=url)
        return False

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.mail_from,
                    "to": [to],
                    "subject": _reset_subject(),
                    "html": _reset_body(url),
                },
            )
        if response.status_code >= 400:
            # Log the status, never the body: it echoes the recipient address.
            log.error("password_reset_email_failed", status=response.status_code)
            return False
        log.info("password_reset_email_sent")
        return True
    except Exception as exc:  # noqa: BLE001 - delivery must never break the request
        log.error("password_reset_email_error", error=str(exc))
        return False
