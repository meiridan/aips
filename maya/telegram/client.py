"""Thin async Telegram Bot API client over httpx.

Only the calls Maya needs: sendMessage, sendChatAction (typing), and webhook
registration. No external Telegram library — keeps the dependency surface small
and avoids a second asyncio app loop competing with FastAPI/uvicorn.
"""

from __future__ import annotations

import httpx

from maya.logging import get_logger

log = get_logger("maya.telegram")

API_BASE = "https://api.telegram.org"
# Telegram rejects message text longer than 4096 chars; we split on this.
MAX_MESSAGE_LEN = 4096


def _chunk(text: str, size: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split text into <=size pieces, preferring newline boundaries."""
    text = text or "..."
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > size:
        window = remaining[:size]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = size
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


class TelegramClient:
    def __init__(self, token: str, *, verify: bool = True) -> None:
        self._token = token
        # `verify=False` mirrors the litellm SSL workaround (maya/llm/service.py)
        # for environments behind TLS-inspecting proxies (e.g. Zscaler).
        self._verify = verify

    def _url(self, method: str) -> str:
        return f"{API_BASE}/bot{self._token}/{method}"

    async def send_message(self, chat_id: int, text: str) -> None:
        async with httpx.AsyncClient(verify=self._verify, timeout=30) as client:
            for piece in _chunk(text):
                resp = await client.post(
                    self._url("sendMessage"),
                    json={"chat_id": chat_id, "text": piece},
                )
                if resp.status_code != 200:
                    log.warning(
                        "telegram_send_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        async with httpx.AsyncClient(verify=self._verify, timeout=10) as client:
            try:
                await client.post(
                    self._url("sendChatAction"),
                    json={"chat_id": chat_id, "action": action},
                )
            except httpx.HTTPError:  # typing indicator is best-effort
                pass

    async def set_webhook(self, url: str, secret: str) -> None:
        async with httpx.AsyncClient(verify=self._verify, timeout=30) as client:
            resp = await client.post(
                self._url("setWebhook"),
                json={"url": url, "secret_token": secret},
            )
            log.info("telegram_set_webhook", url=url, status=resp.status_code)

    async def delete_webhook(self) -> None:
        async with httpx.AsyncClient(verify=self._verify, timeout=30) as client:
            await client.post(self._url("deleteWebhook"))
