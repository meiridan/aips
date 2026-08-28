"""grokbench — measure the xAI API directly, outside the Maya stack.

A real web turn spent 7.1s on one grok-4.6 call for 16 output tokens. From
inside the app there is no way to tell whether that is xAI, litellm, the
Zscaler MITM proxy's TLS handshake, or the 2000-token Hebrew prompt. This talks
to https://api.x.ai/v1 over raw HTTP so each one can be measured on its own.

Diagnostic only. Nothing in maya/ imports this.

    uv run python tools/grokbench/bench.py models
    uv run python tools/grokbench/bench.py run --preset maya -n 3
    uv run python tools/grokbench/bench.py run --preset maya --cold
    uv run python tools/grokbench/bench.py run --preset maya --via-litellm
    uv run python tools/grokbench/bench.py tokenize "שלום עולם"
"""

from __future__ import annotations

import json
import socket
import ssl
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import truststore

truststore.inject_into_ssl()  # certifi alone fails behind Zscaler — see CLAUDE.md

import httpx  # noqa: E402
import typer  # noqa: E402

from maya.config import get_settings  # noqa: E402

API_BASE = "https://api.x.ai/v1"
HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "prompts" / "maya_he.json"

TINY_MESSAGES = [{"role": "user", "content": "Say ok."}]

app = typer.Typer(add_completion=False, help="Measure the xAI API directly.")


def _key() -> str:
    key = get_settings().xai_api_key
    if not key:
        raise typer.BadParameter("XAI_API_KEY is empty (checked .env via maya.config).")
    return key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


def _bare(model: str) -> str:
    """The raw API takes 'grok-4.6'; litellm takes 'xai/grok-4.6'."""
    return model.split("/", 1)[1] if model.startswith("xai/") else model


# ── timing helpers ───────────────────────────────────────────────────────────


def tls_probe(host: str = "api.x.ai", port: int = 443) -> tuple[float, float]:
    """(tcp_ms, tls_ms) for one fresh connection. The Zscaler tax lands here."""
    t0 = time.perf_counter()
    sock = socket.create_connection((host, port), timeout=20)
    t1 = time.perf_counter()
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(sock, server_hostname=host) as tls:
        t2 = time.perf_counter()
        tls.close()
    return (t1 - t0) * 1000, (t2 - t1) * 1000


class Result(dict):
    """One measured call. A dict so --json is free."""


def _summarize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    usage = usage or {}
    details = usage.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
    }


# ── the call, three ways ─────────────────────────────────────────────────────


def call_raw_stream(client: httpx.Client, body: dict[str, Any]) -> Result:
    t0 = time.perf_counter()
    ttft = None
    text = ""
    usage = None
    with client.stream("POST", f"{API_BASE}/chat/completions", json=body) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    text += piece
    total = (time.perf_counter() - t0) * 1000
    return Result(ttft_ms=ttft, total_ms=total, text=text, **_summarize_usage(usage))


def call_raw_blocking(client: httpx.Client, body: dict[str, Any]) -> Result:
    t0 = time.perf_counter()
    resp = client.post(f"{API_BASE}/chat/completions", json=body)
    resp.raise_for_status()
    total = (time.perf_counter() - t0) * 1000
    data = resp.json()
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return Result(ttft_ms=None, total_ms=total, text=text, **_summarize_usage(data.get("usage")))


def call_litellm(body: dict[str, Any], stream: bool) -> Result:
    """The same request through litellm, to price its overhead."""
    import litellm

    litellm.ssl_verify = False  # mirrors maya/llm/service.py
    kwargs = dict(body)
    kwargs["model"] = f"xai/{_bare(kwargs['model'])}"
    kwargs.pop("stream", None)
    kwargs.pop("stream_options", None)

    t0 = time.perf_counter()
    ttft = None
    text = ""
    usage = None
    if stream:
        resp = litellm.completion(**kwargs, stream=True, stream_options={"include_usage": True})
        for chunk in resp:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage = u.model_dump() if hasattr(u, "model_dump") else dict(u)
            for choice in getattr(chunk, "choices", None) or []:
                piece = getattr(getattr(choice, "delta", None), "content", None) or ""
                if piece:
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    text += piece
    else:
        resp = litellm.completion(**kwargs)
        text = resp.choices[0].message.content or ""
        u = getattr(resp, "usage", None)
        usage = (u.model_dump() if hasattr(u, "model_dump") else dict(u)) if u else None
    total = (time.perf_counter() - t0) * 1000
    return Result(ttft_ms=ttft, total_ms=total, text=text, **_summarize_usage(usage))


# ── report ───────────────────────────────────────────────────────────────────


def _fmt(ms: float | None) -> str:
    return "     —" if ms is None else f"{ms:7.0f}"


def _report(model: str, runs: list[Result], label: str, show_text: bool = False) -> None:
    print(f"\n  {model}  ({label})")
    print("    #    ttft_ms  total_ms   tok/s   prompt  out  reasoning")
    for i, r in enumerate(runs, 1):
        out = r["completion_tokens"]
        rate = out / (r["total_ms"] / 1000) if out and r["total_ms"] else 0.0
        print(
            f"    {i}  {_fmt(r['ttft_ms'])}  {_fmt(r['total_ms'])}  {rate:6.1f}"
            f"   {r['prompt_tokens']:6}  {out:4}  {r['reasoning_tokens']:9}"
        )
    totals = [r["total_ms"] for r in runs]
    ttfts = [r["ttft_ms"] for r in runs if r["ttft_ms"] is not None]
    print(
        f"    total  min {min(totals):.0f}  median {statistics.median(totals):.0f}  max {max(totals):.0f} ms"
    )
    if ttfts:
        print(
            f"    ttft   min {min(ttfts):.0f}  median {statistics.median(ttfts):.0f}  max {max(ttfts):.0f} ms"
        )
    if show_text:
        for i, r in enumerate(runs, 1):
            print(f"\n    --- reply {i} ---")
            for line in r["text"].strip().splitlines():
                print(f"    {line}")
    else:
        preview = runs[-1]["text"].strip().replace("\n", " ")[:100]
        print(f"    last reply: {preview}")


# ── commands ─────────────────────────────────────────────────────────────────


@app.command()
def run(
    model: list[str] = typer.Option(["grok-4.6"], "--model", "-m", help="Repeatable."),
    preset: str = typer.Option("maya", help="tiny | maya"),
    prompt_file: Path | None = typer.Option(None, help="JSON message list; overrides --preset."),
    reasoning_effort: str = typer.Option("low", help="none | low | high"),
    max_tokens: int = typer.Option(800),
    temperature: float = typer.Option(0.4),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
    runs: int = typer.Option(3, "-n", help="Calls per model."),
    cold: bool = typer.Option(False, help="Fresh client per run — puts the TLS handshake inside."),
    via_litellm: bool = typer.Option(False, help="Go through litellm instead of raw HTTP."),
    insecure: bool = typer.Option(
        False, help="Skip TLS verification (mirrors litellm.ssl_verify=False)."
    ),
    show_text: bool = typer.Option(False, "--show-text", help="Print every reply in full."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Send the same request N times per model and report the timings."""
    if prompt_file is not None:
        messages = json.loads(prompt_file.read_text(encoding="utf-8"))
    elif preset == "tiny":
        messages = TINY_MESSAGES
    elif preset == "maya":
        messages = json.loads(FIXTURE.read_text(encoding="utf-8"))
    else:
        raise typer.BadParameter(f"unknown preset {preset!r} (tiny | maya)")

    tcp_ms, tls_ms = tls_probe()
    # Header goes to stderr so --json keeps stdout parseable.
    banner = sys.stderr if as_json else sys.stdout
    print(f"\nconnection probe: tcp {tcp_ms:.0f} ms · tls handshake {tls_ms:.0f} ms", file=banner)
    print(
        f"messages: {len(messages)}  ·  runs: {runs}  ·  stream: {stream}  ·  cold: {cold}",
        file=banner,
    )

    everything: dict[str, list[Result]] = {}
    label = ("litellm" if via_litellm else "raw") + (", cold" if cold else ", warm")

    for m in model:
        body: dict[str, Any] = {
            "model": _bare(m),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if reasoning_effort != "none":
            body["reasoning_effort"] = reasoning_effort
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}

        results: list[Result] = []
        client: httpx.Client | None = None
        try:
            for _ in range(runs):
                if via_litellm:
                    results.append(call_litellm(body, stream))
                    continue
                if cold or client is None:
                    if client is not None:
                        client.close()
                    client = httpx.Client(headers=_headers(), timeout=120.0, verify=not insecure)
                fn = call_raw_stream if stream else call_raw_blocking
                results.append(fn(client, body))
        finally:
            if client is not None:
                client.close()

        everything[m] = results
        if not as_json:
            _report(m, results, label, show_text)

    if as_json:
        print(
            json.dumps(
                {
                    "tcp_ms": tcp_ms,
                    "tls_ms": tls_ms,
                    "label": label,
                    "results": everything,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


@app.command()
def models() -> None:
    """List the models this key can reach. Free."""
    with httpx.Client(headers=_headers(), timeout=30.0) as client:
        resp = client.get(f"{API_BASE}/models")
        resp.raise_for_status()
        for item in resp.json().get("data", []):
            print(item.get("id"))


@app.command()
def tokenize(
    text: str = typer.Argument(None, help="Text to tokenize; omit to use the maya fixture."),
    model: str = typer.Option("grok-4.6", "--model", "-m"),
) -> None:
    """True Grok token count, via /v1/tokenize-text.

    This is where the Hebrew scaling factors in maya/conversation/prompt_builder.py
    came from, so it is how they stay checkable.
    """
    if text is None:
        messages = json.loads(FIXTURE.read_text(encoding="utf-8"))
        text = "\n".join(m["content"] for m in messages)
    with httpx.Client(headers=_headers(), timeout=30.0) as client:
        resp = client.post(f"{API_BASE}/tokenize-text", json={"text": text, "model": _bare(model)})
        resp.raise_for_status()
        tokens = resp.json().get("token_ids") or []

    from maya.conversation.prompt_builder import count_tokens

    guess = count_tokens(text, model=f"xai/{_bare(model)}")
    print(f"chars {len(text)}  ·  grok tokens {len(tokens)}  ·  our guard estimates {guess}")
    if tokens:
        ratio = guess / len(tokens)
        verdict = "safe (over-estimates)" if ratio >= 1.0 else "UNSAFE (under-estimates)"
        print(f"guard/actual ratio {ratio:.3f} — {verdict}")


if __name__ == "__main__":
    app()
