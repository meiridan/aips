# Maya — Phase 3 Breakdown

> "Feelings, an evolving relationship, and self-consistency. The moat."
> 6 dependency-ordered sub-phases · deterministic work front-loaded · LLM risk isolated & incremental

**Flow:** `3a Schema → 3b Engines → 3c Genesis → 3d Moment+Prompt → 3e Orchestrator → 3f Memory+Gate`

Derived from `MAYA_CORE_SPEC.md` §P3.1–P3.11 + Appendices A, B, C, E, G, H.
PDF version: `docs/PHASE3_BREAKDOWN.pdf`.

---

## ⚠️ Open Decisions (decide before 3b / 3e)

Two choices are baked into this plan as **recommendations only** — not yet final.

### Decision 1 — When do Maya's feelings fade? (affects 3b)
Feelings cool toward baseline over time (excitement fast, love slow). When does the math run?

- **Lazy on read (recommended)** — compute the fade only when state is fetched (when a chat opens), from hours since `last_updated`. No background process. Simple, self-correcting, right for single-user.
- **Scheduled worker** — a separate always-running process decays every companion periodically, even with nobody chatting. More infra + cost. Overkill at current scale.

*Plain: lazy = do the math when she wakes up. Scheduled = keep a clock ticking forever.*

### Decision 2 — After Maya replies, when does bookkeeping run? (affects 3e)
After each reply she saves memories, updates feelings, bumps counters (~2–4s). Does the user wait?

- **Await-after-send (recommended)** — show the reply instantly, THEN run bookkeeping before the next turn. Fast perceived reply + guaranteed save.
- **Fire-and-forget (spec's literal `asyncio.create_task`)** — reply and bookkeeping start together, don't wait. Slightly faster, but a mid-save disconnect can LOSE the update — the exact lost-message bug already hit in the web UI.

*Plain: await = reply now, save reliably right after. Fire-and-forget = save in background, risk losing it on disconnect.*

**Status:** UNDECIDED — user deciding later. Recommendations both favor simpler + safer over spec-literal.

---

## 3a · Schema & State Models
**Goal:** the entire Phase-3 data layer exists and round-trips. No behavior change yet.
**Risk:** LOW · **No LLM**

**Build**
- **P3.1** Alembic migration `0004_phase3_state.py` — tables: `emotional_state`, `relationship_state`, `relationship_events`, `companion_commitments`; + `companions.personality` (JSONB), `companions.backstory` (TEXT)
- **models.py** — 4 new SQLAlchemy models + Companion field additions (match existing 2.0 `mapped_column` style)
- **P3.2** `maya/companions/templates.py` — 3 templates (flirt / devoted / best_friend)

**Tests:** migration up/down clean; model insert+read round-trip; template load
**Depends on:** nothing. Foundation for all later sub-phases.

---

## 3b · Emotional & Relationship Engines
**Goal:** deterministic state logic — decay + stage transitions + commitments CRUD — fully unit-tested, visible via CLI.
**Risk:** LOW–MED · **No LLM**

**Build**
- **P3.4** `maya/emotional/service.py` + `constants.py` (feeling half-lives, `decay_feeling()`). Decay model per **Decision 1**.
- **P3.5** `maya/relationship/service.py` + `transitions.py` — full Appendix G table + predicates (`has_event`, `has_recent_event`, `days_since_last`…)
- **P3.6** `maya/companions/commitments.py` — CRUD only (`add`, `get_recent`); LLM extraction deferred to 3e
- **P3.11** Upgrade `maya state` CLI — show feelings, stage, intimacy/trust, events, commitments

**Tests:** decay math (1.0→0.5 after one half-life); every stage transition with mock state; commitment CRUD
**Depends on:** 3a (tables + models).

---

## 3c · Genesis — Companion Birth
**Goal:** every seeded companion gets a unique backstory, initial feelings, seed commitments, and a real first message.
**Risk:** MEDIUM · **LLM (one-shot)**

**Build**
- **P3.3** `maya/companions/genesis.py` — Appendix E prompt → `GenesisResult`; uses `main` tier (personality matters)
- `run_genesis()` writes backstory, inits emotional + relationship state, saves seed commitments, seeds Mem0 identity, saves opening assistant message
- Wire into `maya seed` CLI

**Tests:** genesis returns valid structure (mocked LLM); seed runs genesis end-to-end against test DB
**Depends on:** 3a (templates), 3b (emotional/relationship/commitments services), existing MemoryService.

---

## 3d · Moment Analysis & Rich Prompt
**Goal:** classify each moment and assemble the full Phase-3 prompt — built and tested in isolation, not yet in the live loop.
**Risk:** MEDIUM · **LLM (fast tier)**

**Build**
- **P3.7** `maya/conversation/moment_analyzer.py` — Appendix B, `fast` tier, <500ms; invalid JSON/timeout → default `chitchat` (never blocks)
- **P3.9** Rich `prompt_builder.py` — Appendix C template + Appendix H moment guidance; identity / feelings / relationship / moment / memories / commitments / recent / message blocks
- `count_tokens()` via `tiktoken` — fail loud if > 8000 tokens (new dep). Note: tiktoken is OpenAI's tokenizer; for Grok the guard is approximate.

**Tests:** moment analyzer parse + fallback path; prompt assembly snapshot; token-budget guard trips
**Depends on:** 3b (emotional/relationship DTOs), 3a (commitments model).

---

## 3e · Orchestrator Integration
**Goal:** wire everything into the live chat loop — the behavioral leap. Highest-risk sub-phase.
**Risk:** HIGH · **LLM (multi-call)**

**Build**
- **P3.10** Upgrade `Orchestrator.handle_message` — parallel context gather (memory, emotional, relationship, commitments, recent), moment analysis, rich prompt, main LLM call
- **Post-processing** (timing per **Decision 2**): Mem0 extract, emotional update, relationship increment, **P3.6** LLM commitment extraction, event logging, stage-transition eval
- **DebugOrchestrator refactor** — orchestrator emits step events via optional callback; web debug panel subscribes. One code path — kills the 3/10 duplication bug class.

**Tests:** full `handle_message` with mocked LLM; post-processing applies all state updates; debug callback fires expected events
**Depends on:** 3b, 3c, 3d (everything converges here).

---

## 3f · Memory Quality & Gate
**Goal:** richer memories + full Phase-3 gate verification. Ship-readiness.
**Risk:** LOW–MED · **LLM (config)**

**Build**
- **P3.8** `maya/memory/prompts.py` — Appendix A companion-aware extraction prompt; inject into `build_mem0_config` (`custom_fact_extraction_prompt`, `custom_update_memory_prompt`)
- Run full P3 gate (below) + cost check

**Tests / Gate:** qualitative memory richness check; all gate items below pass
**Depends on:** 3e (live loop) for end-to-end validation.

---

## Phase 3 Exit Gate

| Gate item | Verified in |
|---|---|
| `maya seed` produces unique backstory + first message | 3c |
| Emotional state changes between calm vs high-intensity exchanges | 3e |
| Relationship stage transitions correctly (tested) | 3b (logic) · 3e (live) |
| After 24h test-clock, feelings have decayed | 3b |
| No self-contradiction across 20-message identity conversation | 3e + 3f |
| `maya state` shows rich, accurate snapshot | 3b (built) · 3e (populated) |
| Custom Mem0 prompts richer than defaults (qualitative) | 3f |
| All Phase 1 + Phase 2 tests still pass | every sub-phase (regression) |
| LLM cost per turn average < $0.10 | 3f |

---

## Why This Slicing

- **Risk front-loading** — 3a/3b are pure deterministic, fully unit-testable, zero LLM cost. Confidence built before any model is called.
- **Incremental LLM exposure** — one-shot genesis (3c) → isolated prompt/analysis (3d) → full loop (3e). Each LLM surface validated before the next stacks on it.
- **Duplication killed once** — the DebugOrchestrator refactor lands exactly where orchestration grows complex (3e), not before.
- **Every P3.x mapped exactly once** — P3.1→3a, P3.2→3a, P3.3→3c, P3.4→3b, P3.5→3b, P3.6→3b+3e, P3.7→3d, P3.8→3f, P3.9→3d, P3.10→3e, P3.11→3b.
