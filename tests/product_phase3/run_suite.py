"""Run the Phase-3 product memory suite against the live local stack.

Text-in / text-out from the user's perspective. Each case gets a fresh
user+companion, optional seeded Maya backstory/commitments, runs its turns
through the real Orchestrator (cheap tier), and asserts keywords on Maya's
replies plus the user-memory store.

Usage:
    uv run python -m tests.product_phase3.run_suite              # all 200
    uv run python -m tests.product_phase3.run_suite --limit 10   # smoke
    uv run python -m tests.product_phase3.run_suite --concurrency 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete as sa_delete
from sqlalchemy import text

from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, CompanionCommitment, User
from maya.db.session import dispose_engine, get_sessionmaker
from maya.llm.service import LLMService
from maya.logging import configure_logging
from maya.memory.service import MemoryService

from .cases import Probe, ProductCase, all_cases

configure_logging("ERROR")

REPORT_DIR = Path(__file__).parent
MODEL_TIER = "cheap"


# ───────────────────────── result types ─────────────────────────


@dataclass
class ProbeResult:
    msg: str
    response: str
    passed: bool
    reason: str = ""


@dataclass
class CaseResult:
    id: str
    category: str
    name: str
    status: str = "error"            # pass | fail | error
    probes: list[ProbeResult] = field(default_factory=list)
    mem_passed: bool = True
    mem_detail: str = ""
    memories: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


# ───────────────────────── checks ─────────────────────────


def _check_probe(response: str, p: Probe) -> tuple[bool, str]:
    lc = response.lower()
    if p.require and not any(k in lc for k in p.require):
        return False, f"missing any of {p.require}"
    if p.require_all and not all(k in lc for k in p.require_all):
        missing = [k for k in p.require_all if k not in lc]
        return False, f"missing all-required {missing}"
    if p.forbid and any(k in lc for k in p.forbid):
        hit = [k for k in p.forbid if k in lc]
        return False, f"forbidden present {hit}"
    return True, ""


# ───────────────────────── entity lifecycle ─────────────────────────


async def _create(case: ProductCase) -> tuple[uuid.UUID, uuid.UUID]:
    sm = get_sessionmaker()
    async with sm() as session:
        user = User(name="ProductTest", description="phase3 product suite")
        session.add(user)
        await session.flush()
        personality = {"description": case.seed_backstory} if case.seed_backstory else {}
        comp = Companion(
            user_id=user.id,
            name="Maya",
            template_id="test",
            backstory=case.seed_backstory or "",
            personality=personality,
        )
        session.add(comp)
        await session.flush()
        for content, ctype in case.seed_commitments:
            session.add(CompanionCommitment(
                companion_id=comp.id, content=content,
                commitment_type=ctype, importance=0.9,
            ))
        await session.commit()
        return user.id, comp.id


async def _cleanup(uid: uuid.UUID) -> None:
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            await session.execute(sa_delete(User).where(User.id == uid))
            await session.execute(
                text("DELETE FROM maya_memories WHERE payload->>'user_id' = :uid"),
                {"uid": str(uid)},
            )
            await session.commit()
    except Exception:
        pass


# ───────────────────────── per-case runner ─────────────────────────


async def run_case(
    case: ProductCase,
    llm: LLMService,
    memory: MemoryService,
    sem: asyncio.Semaphore,
) -> CaseResult:
    res = CaseResult(id=case.id, category=case.category, name=case.name)
    async with sem:
        t0 = time.monotonic()
        uid = None
        try:
            uid, cid = await _create(case)
            orch = Orchestrator(llm=llm, memory=memory, default_tier=MODEL_TIER)

            for m in case.setup:
                await orch.handle_message(uid, cid, m)

            from .cases import _fillers
            for f in _fillers(case.fillers, seed=hash(case.id) & 0xFFFF):
                await orch.handle_message(uid, cid, f)

            if case.restart_before_probes:
                await asyncio.sleep(2)  # let extraction settle
                orch = Orchestrator(llm=llm, memory=memory, default_tier=MODEL_TIER)

            all_ok = True
            for p in case.probes:
                response = await orch.handle_message(uid, cid, p.msg)
                ok, reason = _check_probe(response, p)
                all_ok = all_ok and ok
                res.probes.append(ProbeResult(p.msg, response, ok, reason))

            # memory-store checks
            mems = await memory.get_all(uid, cid)
            res.memories = [m["text"] for m in mems]
            blob = " ".join(m["text"].lower() for m in mems)
            mem_ok = True
            details = []
            for tok in case.mem_require:
                if tok.lower() not in blob:
                    mem_ok = False
                    details.append(f"mem missing '{tok}'")
            for tok in case.mem_forbid:
                if tok.lower() in blob:
                    mem_ok = False
                    details.append(f"mem LEAK '{tok}'")
            res.mem_passed = mem_ok
            res.mem_detail = "; ".join(details)

            res.status = "pass" if (all_ok and mem_ok) else "fail"
        except Exception as exc:
            res.status = "error"
            res.error = f"{type(exc).__name__}: {exc}"
        finally:
            res.duration_ms = int((time.monotonic() - t0) * 1000)
            if uid is not None:
                await _cleanup(uid)
    return res


# ───────────────────────── orchestration ─────────────────────────


async def run_all(limit: int | None, concurrency: int, category: str | None = None) -> list[CaseResult]:
    cases = all_cases()
    if category:
        cases = [c for c in cases if category in c.category or category in c.id]
    if limit:
        cases = cases[:limit]

    llm = LLMService()
    memory = MemoryService(llm=llm)
    sem = asyncio.Semaphore(concurrency)

    total = len(cases)
    done = 0
    results: list[CaseResult] = []

    async def _wrapped(c: ProductCase) -> CaseResult:
        nonlocal done
        r = await run_case(c, llm, memory, sem)
        done += 1
        mark = {"pass": "✅", "fail": "❌", "error": "⚙️"}.get(r.status, "?")
        print(f"[{done:3d}/{total}] {mark} {r.id:10s} {r.category:22s} {r.duration_ms:6d}ms", flush=True)
        return r

    results = list(await asyncio.gather(*[_wrapped(c) for c in cases]))

    # Retry pass: rerun errored cases sequentially (errors are almost always
    # transient OpenAI 429 rate limits, not product failures).
    by_id = {c.id: c for c in cases}
    errored_ids = [r.id for r in results if r.status == "error"]
    if errored_ids:
        print(f"\n--- retry pass: {len(errored_ids)} errored case(s), sequential ---", flush=True)
        retry_sem = asyncio.Semaphore(1)
        for idx, cid in enumerate(errored_ids):
            await asyncio.sleep(3)  # let the TPM window recover
            r = await run_case(by_id[cid], llm, memory, retry_sem)
            mark = {"pass": "✅", "fail": "❌", "error": "⚙️"}.get(r.status, "?")
            print(f"[retry {idx+1:2d}/{len(errored_ids)}] {mark} {r.id:10s} {r.category}", flush=True)
            for j, existing in enumerate(results):
                if existing.id == cid:
                    results[j] = r
                    break

    await dispose_engine()
    return results


# ───────────────────────── reporting ─────────────────────────


def write_report(results: list[CaseResult]) -> tuple[Path, Path]:

    n = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    errored = sum(1 for r in results if r.status == "error")

    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # JSON
    json_path = REPORT_DIR / "results.json"
    json_path.write_text(json.dumps(
        {
            "generated": ts,
            "total": n, "passed": passed, "failed": failed, "errored": errored,
            "pass_rate": round(100 * passed / n, 1) if n else 0,
            "cases": [
                {
                    "id": r.id, "category": r.category, "name": r.name,
                    "status": r.status, "duration_ms": r.duration_ms,
                    "mem_passed": r.mem_passed, "mem_detail": r.mem_detail,
                    "error": r.error,
                    "probes": [
                        {"msg": p.msg, "response": p.response, "passed": p.passed, "reason": p.reason}
                        for p in r.probes
                    ],
                    "memories": r.memories,
                }
                for r in results
            ],
        },
        indent=2, ensure_ascii=False,
    ))

    # Markdown
    md = ["# Phase 3 Product Memory Suite — Report", "", f"_Generated: {ts}_", ""]
    md.append(f"**{passed}/{n} passed** ({round(100*passed/n,1) if n else 0}%) · "
              f"{failed} failed · {errored} errored · tier=`{MODEL_TIER}`")
    md.append("")
    md.append("## By category")
    md.append("")
    md.append("| Category | Pass | Fail | Err | Total |")
    md.append("|---|---|---|---|---|")
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(1 for r in rs if r.status == "pass")
        f = sum(1 for r in rs if r.status == "fail")
        e = sum(1 for r in rs if r.status == "error")
        md.append(f"| {cat} | {p} | {f} | {e} | {len(rs)} |")
    md.append("")

    fails = [r for r in results if r.status != "pass"]
    if fails:
        md.append("## Failures & errors")
        md.append("")
        for r in fails:
            md.append(f"### {r.id} · {r.category} — `{r.status}`")
            if r.error:
                md.append(f"- error: `{r.error}`")
            if not r.mem_passed:
                md.append(f"- memory: {r.mem_detail}")
            for p in r.probes:
                if not p.passed:
                    md.append(f"- probe: `{p.msg}` → {p.reason}")
                    md.append(f"  - reply: _{p.response[:240]}_")
            md.append("")

    md_path = REPORT_DIR / "REPORT.md"
    md_path.write_text("\n".join(md))
    return md_path, json_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--category", type=str, default=None)
    args = ap.parse_args()

    t0 = time.monotonic()
    results = asyncio.run(run_all(args.limit, args.concurrency, args.category))
    elapsed = time.monotonic() - t0

    n = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    errored = sum(1 for r in results if r.status == "error")
    md_path, json_path = write_report(results)

    print("")
    print("=" * 60)
    print(f"RESULT: {passed}/{n} passed · {failed} failed · {errored} errored")
    print(f"Pass rate: {round(100*passed/n,1) if n else 0}%   ({elapsed:.0f}s, tier={MODEL_TIER})")
    print(f"Report: {md_path}")
    print(f"JSON:   {json_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
