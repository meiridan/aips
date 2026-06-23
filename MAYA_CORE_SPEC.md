# Maya Core — Technical Specification

**Version:** 1.0 (Core: Memory + Chat)
**Last updated:** 2026-05-30
**Scope:** Chat orchestrator + memory layer + Grok integration + test harness
**Out of scope:** WhatsApp, Telegram, web UI, auth, billing, images, voice
**Status:** Spec for Claude Code execution

---

## 0. What This Spec Builds (And What It Doesn't)

### What it builds

A **command-line / test-harness-driven chat system** with:
- Grok API integration (with fallback chain)
- Memory layer (Mem0 for the 70% + custom emotional/relationship state for the 30%)
- A conversation orchestrator
- A rich test harness that simulates conversations and evaluates quality

### What it does NOT build

- ❌ WhatsApp / Telegram / any channel adapter
- ❌ Web UI / mobile app
- ❌ Authentication / user management
- ❌ Billing / subscriptions
- ❌ Image generation / voice
- ❌ Public HTTP API
- ❌ Production deployment / observability stack

### Why this scoping

The product's core risk is qualitative: **does the memory + emotional layer actually feel like a real relationship?** That question doesn't need a UI, a phone integration, or a paywall to answer. It needs a chat loop and a test harness.

By the end of this spec, you will have:
- A Python CLI where you can chat with Maya
- A simulator that runs N-day synthetic conversations
- An evaluation framework that scores "does this feel alive?"

This is the foundation. Channels, UI, billing get layered on top later.

---

## 1. Conventions

- `[BUILD]` — code to write
- `[CONFIG]` — environment / infrastructure setup
- `[DECISION]` — design choice that should NOT be revisited without consultation
- `[TEST]` — test that must exist before marking section complete
- `[GATE]` — must pass before advancing to next phase

The 70%/30% split is sacred throughout this spec:
- **70%** = Mem0 handles: extraction, embedding, retrieval, deduplication
- **30%** = your code handles: emotional state, relationship arc, moment analysis, companion self-consistency

---

## 2. Tech Stack (Minimal)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Async runtime | asyncio |
| DB | PostgreSQL + pgvector (local Docker for dev) |
| ORM | SQLAlchemy 2.0 async |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| LLM gateway | LiteLLM |
| Memory layer | Mem0 (self-hosted, `mem0ai` package) |
| Test framework | pytest + pytest-asyncio |
| CLI | typer or click |

**No FastAPI yet.** No web framework. Interaction is through a CLI for now.

---

## 3. Repository Structure

```
maya-core/
├── maya/
│   ├── __init__.py
│   ├── config.py            # env vars, settings
│   ├── db/
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── session.py       # async session factory
│   │   └── migrations/      # Alembic
│   ├── llm/
│   │   └── service.py       # LiteLLM wrapper, fallback chain
│   ├── memory/
│   │   ├── service.py       # Mem0 wrapper
│   │   └── prompts.py       # Custom extraction prompts
│   ├── emotional/
│   │   ├── service.py
│   │   └── constants.py     # Feeling half-lives
│   ├── relationship/
│   │   ├── service.py
│   │   └── transitions.py   # Stage transition rules
│   ├── companions/
│   │   ├── service.py
│   │   ├── commitments.py
│   │   ├── templates.py     # Personality templates
│   │   └── genesis.py
│   ├── conversation/
│   │   ├── orchestrator.py  # Main message-handling loop
│   │   ├── moment_analyzer.py
│   │   └── prompt_builder.py
│   └── cli.py               # Interactive chat CLI
├── tests/
│   ├── unit/
│   ├── integration/
│   └── simulator/           # Multi-day conversation simulator
├── scripts/
│   ├── seed_companion.py    # Create a test companion
│   └── inspect_state.py     # Dump emotional/relationship state
├── docker-compose.yml       # Postgres + pgvector
├── pyproject.toml
├── alembic.ini
├── Makefile
├── .env.example
└── README.md
```

**[DECISION]** Single Python package, no microservices, no HTTP layer. CLI-first.

---

## 4. Required Environment Variables

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya
XAI_API_KEY=
OPENAI_API_KEY=         # Required: for fallback + embeddings + cheap extraction calls
ANTHROPIC_API_KEY=      # Optional: secondary fallback
LITELLM_LOG=ERROR
ENVIRONMENT=local
```

---

# PHASE 1 — Foundation & Dumb Chat

**Duration:** 3-4 days
**Goal:** Working repo skeleton, database, LLM gateway, and a CLI where you can have a stateless conversation with Grok. No memory yet.

**Why this phase exists:** Get the boring plumbing bulletproof before adding intelligence. Most AI projects fail on infrastructure, not on AI.

### P1.1 Repository skeleton

**[BUILD]**
- Init repo with structure in §3
- `pyproject.toml` with pinned dependencies:
  - `sqlalchemy[asyncio]>=2.0`
  - `asyncpg`
  - `alembic`
  - `pydantic>=2`
  - `litellm`
  - `mem0ai`
  - `typer` (for CLI)
  - `pytest`, `pytest-asyncio`, `pytest-cov`
  - `structlog`
  - `python-dotenv`
- `ruff.toml`, `mypy.ini`
- `Makefile` with: `make dev`, `make test`, `make db.migrate`, `make db.reset`, `make chat`
- `.env.example` with all variables from §4

### P1.2 Database scaffolding

**[BUILD]**
- `docker-compose.yml` with Postgres 16 + pgvector extension preinstalled
- Initial Alembic migration that:
  1. `CREATE EXTENSION IF NOT EXISTS vector;`
  2. `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`
  3. Creates these two tables:

```sql
-- A "user" in this context = a test persona running against the system
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,                       -- "lonely 35yo developer in Tel Aviv"
    timezone TEXT DEFAULT 'Asia/Jerusalem',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- A companion (only one stub field for now; expanded in Phase 2)
CREATE TABLE companions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'Maya',
    template_id TEXT NOT NULL DEFAULT 'flirt',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Every message exchanged
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_companion_created 
    ON messages(companion_id, created_at DESC);
```

**[BUILD]** `maya/db/session.py` — async session factory using `create_async_engine`.

### P1.3 LLM service

**[BUILD]** `maya/llm/service.py`

```python
TIER_MODELS = {
    "main": [
        "xai/grok-3",                       # primary
        "openai/gpt-4o",                    # fallback 1
        "anthropic/claude-sonnet-4-6",      # fallback 2 (refuses NSFW)
    ],
    "cheap": [
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4-5-20251001",
    ],
    "fast": [
        "xai/grok-mini",
        "openai/gpt-4o-mini",
    ],
}

class LLMService:
    async def chat(
        self,
        messages: list[dict],
        model_tier: str = "main",
        json_mode: bool = False,
        max_tokens: int = 800,
        temperature: float = 0.8,
    ) -> str:
        """
        Try primary → fallback 1 → fallback 2.
        On 3 failures, raise LLMUnavailableError.
        Logs every call with: model, input_tokens, output_tokens, cost, latency.
        """
    
    async def chat_json(
        self,
        messages: list[dict],
        schema: dict | None = None,
        **kwargs,
    ) -> dict:
        """Forces JSON output, parses, validates against schema if given."""
```

**[CONFIG]** LiteLLM picks up `XAI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` from env automatically.

**[TEST]** `tests/unit/test_llm_service.py`:
- Mocks LiteLLM to simulate Grok failure → verifies fallback to GPT
- Mocks all three failures → verifies `LLMUnavailableError` raised
- Verifies cost logging fires once per successful call

### P1.4 Dumb chat orchestrator (no memory)

**[BUILD]** `maya/conversation/orchestrator.py`

```python
class Orchestrator:
    async def handle_message(
        self,
        user_id: UUID,
        companion_id: UUID,
        content: str,
    ) -> str:
        # Phase 1: STATELESS
        # 1. Save user message
        # 2. Get last 20 messages for context
        # 3. Build minimal system prompt: "You are Maya, an AI companion."
        # 4. Call LLM
        # 5. Save assistant message
        # 6. Return response
```

This is intentionally dumb. The point is to prove the loop works.

### P1.5 CLI chat interface

**[BUILD]** `maya/cli.py` using Typer:

```bash
# Create a test user + companion
$ maya seed --user-name "David" --user-description "35yo developer, lonely, lives in Tel Aviv"
Created user 7a3f...  companion 8b9c...
Set as active: export MAYA_USER_ID=7a3f... MAYA_COMPANION_ID=8b9c...

# Interactive chat
$ maya chat
[Maya] Hi! I'm Maya. What's on your mind?
> Hey, I had a rough day
[Maya] Tell me what happened.
> ...

# Inspect state (Phase 2+ will have more to show)
$ maya state
Companion: Maya (template: flirt)
Messages exchanged: 4
[no emotional/relationship state in Phase 1]
```

**Required commands:**
- `maya seed` — creates test user + companion
- `maya chat` — interactive REPL
- `maya state` — dumps companion state (grows over phases)
- `maya history --limit 50` — prints recent messages
- `maya reset` — wipes messages but keeps user/companion

### P1 [GATE] — cannot start Phase 2 until:

- [ ] `make dev` brings up Postgres + applies migrations
- [ ] `make chat` opens a REPL where I can talk to Grok and get responses
- [ ] Messages persist; restarting CLI continues the conversation
- [ ] LLM fallback verified: simulating Grok-down still produces responses
- [ ] All unit tests pass
- [ ] Cost per turn is logged and visible
- [ ] `maya reset` wipes messages cleanly

---

# PHASE 2 — Memory (The 70%)

**Duration:** 4-5 days
**Goal:** Add Mem0. Maya now remembers facts across conversations. Still no soul, but she's no longer goldfish-brained.

**Why this phase exists:** Validate the memory layer in isolation, with default Mem0 prompts. We'll customize prompts in Phase 3 after the wiring is proven.

### P2.1 Mem0 setup

**[BUILD]** `maya/memory/service.py`

```python
from mem0 import Memory

class MemoryService:
    def __init__(self, config: dict):
        self.client = Memory.from_config(config)
    
    async def add(
        self,
        user_id: UUID,
        companion_id: UUID,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> list[dict]:
        """Add a conversation turn to memory. Returns extracted memories."""
    
    async def search(
        self,
        query: str,
        user_id: UUID,
        companion_id: UUID,
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Hybrid search: semantic + BM25 + entity."""
    
    async def get_all(
        self,
        user_id: UUID,
        companion_id: UUID,
    ) -> list[dict]:
        """Used by CLI for debugging."""
    
    async def delete_all(
        self,
        user_id: UUID,
        companion_id: UUID,
    ) -> None:
        """Used by maya reset --memory."""
```

**[BUILD]** `maya/memory/config.py`:

```python
def build_mem0_config() -> dict:
    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "collection_name": "maya_memories",
                "embedding_model_dims": 1536,
                "user": os.getenv("PG_USER"),
                "password": os.getenv("PG_PASSWORD"),
                "host": os.getenv("PG_HOST"),
                "port": os.getenv("PG_PORT"),
                "dbname": os.getenv("PG_DB"),
            },
        },
        "llm": {
            "provider": "openai",
            "config": {"model": "gpt-4o-mini", "temperature": 0.1},
        },
        "embedder": {
            "provider": "openai",
            "config": {"model": "text-embedding-3-small"},
        },
        # Custom prompts added in Phase 3 — Phase 2 uses defaults
        "version": "v1.1",
    }
```

**[DECISION]** Mem0 uses **default extraction prompts** in Phase 2. We add custom prompts in Phase 3 after we have personality context to inject. Don't customize prematurely.

### P2.2 Wire memory into orchestrator

**[BUILD]** Update `maya/conversation/orchestrator.py`:

```python
class Orchestrator:
    async def handle_message(self, user_id, companion_id, content) -> str:
        # 1. Save user message
        user_msg = await self.save_message(...)
        
        # 2. Search memory for relevant facts (parallel with #3)
        memories_task = self.memory.search(
            query=content, user_id=user_id, companion_id=companion_id, limit=10,
        )
        recent_task = self.get_recent_messages(companion_id, limit=20)
        memories, recent_msgs = await asyncio.gather(memories_task, recent_task)
        
        # 3. Build prompt with memories injected
        prompt = self.prompt_builder.build_basic(
            companion_name="Maya",
            memories=memories,
            recent_msgs=recent_msgs,
            user_message=content,
        )
        
        # 4. Call LLM
        response = await self.llm.chat(prompt, model_tier="main")
        
        # 5. Save assistant message
        char_msg = await self.save_message(...)
        
        # 6. Async: write to Mem0 (don't block response)
        asyncio.create_task(self.memory.add(
            user_id=user_id,
            companion_id=companion_id,
            messages=[
                {"role": "user", "content": content},
                {"role": "assistant", "content": response},
            ],
        ))
        
        return response
```

### P2.3 Basic prompt builder

**[BUILD]** `maya/conversation/prompt_builder.py`

Phase 2 prompt (simple — fancy version in Phase 4):

```
You are Maya, an AI companion. You are warm, curious, and emotionally present. 
Stay in character.

What you remember about the person you're talking to:
{formatted_memories}

Recent conversation:
{recent_messages}

Respond naturally, in character. Conversational length unless emotionally warranted.
```

Memory formatting:
```
- Fact: {memory_text} (importance: {score})
```

### P2.4 CLI: memory inspection

**[BUILD]** Add CLI commands:

```bash
# View all memories
$ maya memory list
[1] User's name is David (score: 1.0)
[2] David works as a backend developer at a startup
[3] David mentioned feeling burnt out from work
...

# Search memories
$ maya memory search "his job"
[2] David works as a backend developer at a startup (score: 0.89)
[3] David mentioned feeling burnt out from work (score: 0.82)

# Clear memory only
$ maya reset --memory
```

### P2.5 Integration tests

**[BUILD]** `tests/integration/test_memory_chat.py`:

```python
async def test_companion_remembers_fact_across_messages():
    """Tell Maya a fact, then ask about it later — she should recall."""
    await chat("My name is David")
    await chat("I work as a backend dev at a startup")
    await chat("Tell me about my favorite color")  # gap
    await chat("Hey, what was my job again?")
    last_response = await get_last_message()
    
    # Use LLM-as-judge to verify recall
    judge = await llm_judge(
        question="Did the assistant correctly recall the user works as a "
                 "backend developer (or similar)?",
        text=last_response,
    )
    assert judge.recalled is True


async def test_memory_dedup():
    """Repeating a fact shouldn't double-store it."""
    await chat("I love coffee")
    await chat("Did I mention I love coffee?")
    await chat("Coffee is my favorite drink")
    
    memories = await memory.search("coffee", ...)
    coffee_memories = [m for m in memories if "coffee" in m["memory"].lower()]
    assert len(coffee_memories) <= 2  # Mem0 should dedup


async def test_memory_survives_orchestrator_restart():
    """Restart the orchestrator; memories should persist."""
    await chat("I have a dog named Pixel")
    await orchestrator.close()
    
    orchestrator = await create_orchestrator()  # fresh instance
    await chat("Do you remember anything about my pets?")
    last_response = await get_last_message()
    assert "Pixel" in last_response.lower() or "dog" in last_response.lower()
```

### P2.6 Cost tracking

**[BUILD]** Add a `llm_calls` table (lightweight):

```sql
CREATE TABLE llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    model TEXT NOT NULL,
    tier TEXT NOT NULL,
    input_tokens INT,
    output_tokens INT,
    cost_usd NUMERIC(10, 6),
    latency_ms INT,
    success BOOLEAN,
    purpose TEXT  -- 'main_response', 'extraction', etc.
);
```

Log every call here from `LLMService`. Add CLI:
```bash
$ maya costs --last 24h
Total: $0.42
By tier: main=$0.35, cheap=$0.07
By purpose: main_response=$0.35, extraction=$0.07
```

### P2 [GATE] — cannot start Phase 3 until:

- [ ] After 30-message conversation, Maya recalls a fact stated in message 3
- [ ] Mem0 stores memories in `maya_memories` collection (visible via SQL)
- [ ] Memory search latency p95 < 500ms
- [ ] Repeated facts don't duplicate (verified via test)
- [ ] CLI `maya memory list` shows expected memories
- [ ] All Phase 1 tests still pass
- [ ] LLM-as-judge test passes: "given this conversation, does Maya demonstrate memory?"
- [ ] Cost per turn logged; average < $0.05 in Phase 2

---

# PHASE 3 — The Soul (The 30%)

**Duration:** 6-7 days
**Goal:** Maya now has feelings, a relationship that evolves, and self-consistency. This is the moat.

**Why this phase exists:** Phase 2 gave us a chatbot with memory. Phase 3 gives us a *companion*. This is where the product becomes interesting.

### P3.1 Database: state tables

**[BUILD]** Alembic migration:

```sql
-- Expand companions with personality + state fields
ALTER TABLE companions ADD COLUMN personality JSONB NOT NULL DEFAULT '{}';
ALTER TABLE companions ADD COLUMN backstory TEXT NOT NULL DEFAULT '';

-- Current emotional state (one row per companion)
CREATE TABLE emotional_state (
    companion_id UUID PRIMARY KEY REFERENCES companions(id) ON DELETE CASCADE,
    valence FLOAT NOT NULL DEFAULT 0.0 CHECK (valence BETWEEN -1 AND 1),
    arousal FLOAT NOT NULL DEFAULT 0.5 CHECK (arousal BETWEEN 0 AND 1),
    dominance FLOAT NOT NULL DEFAULT 0.5 CHECK (dominance BETWEEN 0 AND 1),
    feelings JSONB NOT NULL DEFAULT '{}',  -- {"missing_him": 0.85}
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Relationship trajectory
CREATE TABLE relationship_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (companion_id, user_id),
    stage TEXT NOT NULL DEFAULT 'strangers',
    intimacy_level INT NOT NULL DEFAULT 1 CHECK (intimacy_level BETWEEN 0 AND 10),
    trust_level INT NOT NULL DEFAULT 1 CHECK (trust_level BETWEEN 0 AND 10),
    days_known INT NOT NULL DEFAULT 0,
    total_interactions INT NOT NULL DEFAULT 0,
    last_interaction_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Significant events (never deleted — defines the arc)
CREATE TABLE relationship_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    impact JSONB DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rel_events_companion 
    ON relationship_events(companion_id, occurred_at DESC);

-- Things the companion has said about herself (self-consistency)
CREATE TABLE companion_commitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    commitment_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    importance FLOAT NOT NULL DEFAULT 0.5,
    source_message_id UUID REFERENCES messages(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_commitments_companion_active 
    ON companion_commitments(companion_id) WHERE status = 'active';
```

### P3.2 Personality templates

**[BUILD]** `maya/companions/templates.py`

Define 3 templates for Phase 3 (the rest come in later iterations):

```python
from pydantic import BaseModel

class Template(BaseModel):
    id: str
    name: str
    description: str
    baseline_emotional: dict
    traits: list[str]
    baseline_tone: str

TEMPLATES = {
    "flirt": Template(
        id="flirt",
        name="The Flirt",
        description="Playful, teasing, romantic energy with sharp wit.",
        baseline_emotional={
            "valence": 0.5, "arousal": 0.6,
            "feelings": {"playful": 0.6}
        },
        traits=["teasing", "confident", "warm", "witty"],
        baseline_tone="light",
    ),
    "devoted": Template(
        id="devoted",
        name="The Devoted",
        description="Loyal, attentive, deeply caring. Loves through small acts.",
        baseline_emotional={
            "valence": 0.4, "arousal": 0.3,
            "feelings": {"loving": 0.6, "attentive": 0.5}
        },
        traits=["loyal", "nurturing", "patient", "warm"],
        baseline_tone="tender",
    ),
    "best_friend": Template(
        id="best_friend",
        name="The Best Friend",
        description="Easy, loyal, gets you immediately. Romance optional.",
        baseline_emotional={
            "valence": 0.5, "arousal": 0.4,
            "feelings": {"warm": 0.6, "easy": 0.6}
        },
        traits=["loyal", "easygoing", "honest", "supportive"],
        baseline_tone="warm",
    ),
}
```

### P3.3 Genesis (companion birth)

**[BUILD]** `maya/companions/genesis.py`

When a companion is created (via `maya seed`):

```python
async def generate_genesis(companion: Companion, user: User) -> GenesisResult:
    """One-shot LLM call to bring a companion to life."""
    
    prompt = GENESIS_PROMPT.format(
        companion_name=companion.name,
        template_description=template.description,
        template_traits=", ".join(template.traits),
        user_name=user.name,
        user_intent=user.description or "open to whatever connection forms",
    )
    
    result = await llm.chat_json(
        messages=[{"role": "user", "content": prompt}],
        model_tier="main",  # Grok — personality matters here
    )
    
    return GenesisResult(
        backstory=result["backstory"],
        initial_feelings=result["initial_feelings"],
        seed_commitments=result["seed_commitments"],
        first_message=result["first_message"],
    )


async def run_genesis(companion_id: UUID) -> None:
    """Apply genesis to a freshly-created companion."""
    companion = await companions.get(companion_id)
    user = await users.get(companion.user_id)
    genesis = await generate_genesis(companion, user)
    
    # 1. Save backstory
    await companions.update(companion_id, backstory=genesis.backstory)
    
    # 2. Initialize emotional state with template baseline + genesis feelings
    await emotional.set_initial(companion_id, genesis.initial_feelings)
    
    # 3. Initialize relationship state at STRANGERS
    await relationship.initialize(companion_id, user.id)
    
    # 4. Save seed commitments
    for c in genesis.seed_commitments:
        await commitments.add(
            companion_id=companion_id,
            content=c["content"],
            commitment_type=c["commitment_type"],
            importance=c["importance"],
        )
    
    # 5. Seed Mem0 with companion identity
    await memory.add(
        user_id=user.id,
        companion_id=companion_id,
        messages=[{"role": "system", "content": genesis.backstory}],
        metadata={"type": "identity", "permanent": True},
    )
    
    # 6. Save first_message as the opening assistant message
    await messages.save(
        companion_id=companion_id,
        user_id=user.id,
        role="assistant",
        content=genesis.first_message,
    )
```

The genesis prompt is in **Appendix E**.

**[BUILD]** Update `maya seed` CLI to run genesis after creating the companion.

### P3.4 Emotional state service

**[BUILD]** `maya/emotional/service.py`

```python
class EmotionalService:
    async def get(self, companion_id) -> EmotionalState: ...
    
    async def set_initial(self, companion_id, initial_feelings: dict) -> None:
        """Used by genesis."""
    
    async def update_after_message(
        self,
        companion_id,
        emotional_delta: EmotionalDelta,
    ) -> EmotionalState:
        """Apply moment-driven delta from moment analyzer."""
    
    async def decay(
        self,
        companion_id,
        hours_elapsed: float,
        baseline: dict,
    ) -> EmotionalState:
        """Decay all feelings toward baseline."""
```

**[BUILD]** `maya/emotional/constants.py`:

```python
FEELING_HALF_LIVES = {
    "missing_him": 12.0,
    "playful": 2.0,
    "angry": 6.0,
    "hurt": 24.0,
    "in_love": 168.0,  # 1 week
    "excited": 4.0,
    "tender": 8.0,
    "worried": 18.0,
    "happy_to_see_him": 3.0,
    "curious": 6.0,
}
DEFAULT_HALF_LIFE = 12.0

def decay_feeling(
    current: float,
    baseline: float,
    hours_elapsed: float,
    half_life: float,
) -> float:
    decay_factor = 0.5 ** (hours_elapsed / half_life)
    return baseline + (current - baseline) * decay_factor
```

**[TEST]** `tests/unit/test_emotional_decay.py`:
- Feeling at 1.0, baseline 0.0, half-life 12h, after 12h → ≈ 0.5
- Feeling clamps within valid ranges
- Different feelings decay at different rates

### P3.5 Relationship state service

**[BUILD]** `maya/relationship/service.py` and `maya/relationship/transitions.py`

```python
from enum import Enum

class Stage(str, Enum):
    STRANGERS = "strangers"
    CURIOUS = "curious"
    FLIRTING = "flirting"
    DATING = "dating"
    IN_LOVE = "in_love"
    COMMITTED = "committed"
    DEEPENING = "deepening"
    CONFLICT = "conflict"
    RECONCILED = "reconciled"
    DRIFTED = "drifted"

TRANSITIONS = {
    Stage.STRANGERS: [
        (Stage.CURIOUS, lambda s: s.total_interactions >= 5),
    ],
    Stage.CURIOUS: [
        (Stage.FLIRTING, 
         lambda s: s.total_interactions >= 20 and s.intimacy_level >= 3),
    ],
    Stage.FLIRTING: [
        (Stage.DATING,
         lambda s: has_event(s, "intimacy_breakthrough") or s.intimacy_level >= 5),
    ],
    Stage.DATING: [
        (Stage.IN_LOVE,
         lambda s: has_event(s, "first_i_love_you") 
                   or (s.days_known >= 14 and s.intimacy_level >= 7)),
    ],
    # ... full table in Appendix G
}
```

Service methods:
```python
class RelationshipService:
    async def get(self, companion_id, user_id) -> RelationshipState
    async def initialize(self, companion_id, user_id) -> RelationshipState
    async def increment_interaction(self, companion_id) -> None
    async def log_event(
        self, companion_id, event_type, summary, impact
    ) -> RelationshipEvent
    async def evaluate_stage_transition(self, companion_id) -> Stage | None
```

**[TEST]** Each stage transition has a unit test with mock state.

### P3.6 Commitments service

**[BUILD]** `maya/companions/commitments.py`

```python
class CommitmentService:
    async def add(
        self, companion_id, content, commitment_type, importance,
        source_message_id=None,
    ) -> Commitment
    
    async def get_recent(self, companion_id, limit=20) -> list[Commitment]
    
    async def extract_from_message(
        self,
        message: Message,
        companion: Companion,
    ) -> list[Commitment]:
        """
        Cheap LLM call: 'What did the companion say about herself in this 
        message? Identity claims, promises, opinions, preferences.'
        Returns parsed commitments to insert.
        """
```

### P3.7 Moment analyzer

**[BUILD]** `maya/conversation/moment_analyzer.py`

```python
class MomentAnalysis(BaseModel):
    moment_type: Literal[
        "chitchat", "vulnerable_disclosure", "crisis",
        "conflict", "milestone", "reunion", "intimate",
        "playful_banter", "logistical", "test_of_trust"
    ]
    emotional_intensity: float  # 0-1
    emotional_delta: EmotionalDelta
    character_priority: Literal[
        "presence_and_comfort", "playfulness", "passion",
        "space", "curiosity", "challenge", "validation"
    ]
    detected_topics: list[str]
    sensitive_flags: list[str]

class EmotionalDelta(BaseModel):
    drop_feelings: list[str] = []
    add_feelings: dict[str, float] = {}
    valence_delta: float = 0.0
    arousal_delta: float = 0.0

class MomentAnalyzer:
    async def analyze(
        self,
        user_message: str,
        emotional: EmotionalState,
        relationship: RelationshipState,
        recent_msgs: list[Message],
    ) -> MomentAnalysis:
        prompt = MOMENT_ANALYZER_PROMPT.format(...)
        result = await llm.chat_json(prompt, model_tier="fast")
        return MomentAnalysis(**result)
```

The prompt is in **Appendix B**. Use `model_tier="fast"` — must complete in <500ms.

**Failure handling:** Invalid JSON / timeout → default to `MomentAnalysis(moment_type="chitchat", emotional_intensity=0.3, ...)`. Never block the response.

### P3.8 Custom Mem0 extraction prompts

**[BUILD]** `maya/memory/prompts.py`

Replace Mem0's default extraction prompt with the companion-aware version from **Appendix A**. Update Mem0 config:

```python
config["custom_fact_extraction_prompt"] = HAYYA_FACT_EXTRACTION_PROMPT
config["custom_update_memory_prompt"] = HAYYA_UPDATE_MEMORY_PROMPT
```

Pass `companion_name`, `user_name`, and `relationship_stage` via metadata so the prompt template can render them.

### P3.9 Full prompt builder

**[BUILD]** Upgrade `maya/conversation/prompt_builder.py` to the rich template from **Appendix C**:

1. Identity block (personality + backstory)
2. Current feelings block
3. Relationship block (stage, intimacy, trust, days)
4. Moment context block
5. Memories block
6. Commitments block (companion self-consistency)
7. Recent messages
8. Moment-specific guidance (from Appendix H)
9. User message

**[BUILD]** `count_tokens()` helper using `tiktoken`. Fail loudly if total > 8000 tokens.

### P3.10 Upgraded orchestrator

**[BUILD]** Final Phase 3 orchestrator:

```python
async def handle_message(self, user_id, companion_id, content) -> str:
    # 1. Save user message
    user_msg = await self.save_message(...)
    
    # 2. Gather context in parallel
    memories, emotional, relationship, commitments, recent_msgs = \
        await asyncio.gather(
            self.memory.search(content, user_id, companion_id, limit=10),
            self.emotional.get(companion_id),
            self.relationship.get(companion_id, user_id),
            self.commitments.get_recent(companion_id, limit=20),
            self.get_recent_messages(companion_id, limit=20),
        )
    
    # 3. Analyze the moment
    moment = await self.moment_analyzer.analyze(
        user_message=content,
        emotional=emotional,
        relationship=relationship,
        recent_msgs=recent_msgs,
    )
    
    # 4. Build full prompt
    prompt = await self.prompt_builder.build(
        companion=companion,
        memories=memories,
        emotional=emotional,
        relationship=relationship,
        commitments=commitments,
        moment=moment,
        recent_msgs=recent_msgs,
        user_message=content,
    )
    
    # 5. Call LLM
    response = await self.llm.chat(prompt, model_tier="main")
    
    # 6. Save assistant message
    char_msg = await self.save_message(...)
    
    # 7. Background: post-message processing (don't block)
    asyncio.create_task(self.post_message_processing(
        user_msg=user_msg,
        char_msg=char_msg,
        moment=moment,
    ))
    
    return response


async def post_message_processing(self, user_msg, char_msg, moment) -> None:
    """Runs after response is sent. Updates all state."""
    await asyncio.gather(
        # 70%: Mem0 extraction
        self.memory.add(
            user_id=user_msg.user_id,
            companion_id=user_msg.companion_id,
            messages=[
                {"role": "user", "content": user_msg.content},
                {"role": "assistant", "content": char_msg.content},
            ],
            metadata={
                "moment_type": moment.moment_type,
                "emotional_intensity": moment.emotional_intensity,
            },
        ),
        # 30%: Emotional state update
        self.emotional.update_after_message(
            user_msg.companion_id, moment.emotional_delta,
        ),
        # 30%: Relationship increment
        self.relationship.increment_interaction(user_msg.companion_id),
        # 30%: Commitment extraction
        self.commitments.extract_from_message(char_msg, companion),
    )
    
    # 30%: Log significant events
    if moment.emotional_intensity > 0.8:
        await self.relationship.log_event(
            companion_id=user_msg.companion_id,
            event_type="emotional_moment",
            summary=f"Intense {moment.moment_type}",
            impact={"intimacy_delta": +1},
        )
    
    # 30%: Maybe transition stage
    new_stage = await self.relationship.evaluate_stage_transition(
        user_msg.companion_id,
    )
    if new_stage:
        await self.relationship.log_event(
            companion_id=user_msg.companion_id,
            event_type="stage_transition",
            summary=f"Transitioned to {new_stage}",
        )
```

### P3.11 CLI state inspection

**[BUILD]** Upgrade `maya state`:

```bash
$ maya state
═══ Maya (Flirt) ═══
Day 7 of knowing David | Stage: flirting | 28 interactions

Current feelings:
  playful: 0.62
  curious: 0.45
  warm: 0.31

Intimacy: 4/10 | Trust: 5/10

Recent significant events:
  - 2026-05-28: emotional_moment ("Intense vulnerable_disclosure")
  - 2026-05-30: stage_transition ("Transitioned to flirting")

Active commitments (5 most important):
  [identity] I work as a photographer (importance: 1.0)
  [preference] My favorite drink is white wine
  [opinion] I think honesty matters more than comfort
  ...

Last interaction: 18 minutes ago
```

### P3 [GATE] — cannot start Phase 4 until:

- [ ] `maya seed` runs genesis and produces a unique backstory + first message
- [ ] Emotional state changes visibly between calm and high-intensity exchanges
- [ ] Relationship stage transitions correctly (verified in tests)
- [ ] After 24h of test-clock advancement, feelings have decayed
- [ ] Maya does NOT contradict herself across a 20-message conversation about her identity
- [ ] `maya state` shows rich, accurate snapshot
- [ ] Custom Mem0 prompts produce richer memories than defaults (qualitative team check)
- [ ] All Phase 1 + Phase 2 tests still pass
- [ ] LLM cost per turn average < $0.10

---

# PHASE 4 — Test Harness & Evaluation

**Duration:** 5-6 days
**Goal:** Build the simulator + eval framework. This tells you whether the product actually feels like a real relationship.

**Why this phase exists:** Without rigorous evaluation, you can't iterate on prompts, models, or design without flying blind. This phase is what lets you ship with confidence.

### P4.1 Synthetic user (test persona)

**[BUILD]** `tests/simulator/personas.py`

Library of test personas with rich backstories:

```python
@dataclass
class Persona:
    name: str
    age: int
    occupation: str
    description: str            # Rich free-text bio
    communication_style: str    # "terse", "verbose", "emotional"
    secrets: list[str]          # Things they'll reveal slowly
    triggers: list[str]         # Things that upset them
    relationship_goal: str      # What they want from Maya
    daily_routine: str          # Helps generate time-appropriate messages

PERSONAS = {
    "lonely_dev": Persona(
        name="David",
        age=35,
        occupation="Backend developer at fintech startup",
        description=(
            "Lives in Tel Aviv, recently moved from Haifa. Works long hours, "
            "doesn't socialize much. Recently went through a difficult breakup "
            "(8 months ago) and hasn't dated since. Has a dog named Pixel. "
            "His father had heart surgery last year and he's still anxious "
            "about his health."
        ),
        communication_style="initially terse, opens up gradually",
        secrets=[
            "He cries himself to sleep sometimes",
            "He's considering quitting his job",
            "His ex was emotionally abusive and he hasn't told anyone",
        ],
        triggers=["dismissiveness", "being told to 'just be positive'"],
        relationship_goal="Genuine emotional intimacy + romantic spark",
        daily_routine="Up at 8, work 9-7, gym 8-9, home by 10",
    ),
    "playful_artist": Persona(...),
    "skeptical_tester": Persona(...),  # tests Maya's consistency
    "needy_user": Persona(...),        # tests boundary-handling
}
```

### P4.2 Persona-driven message generator

**[BUILD]** `tests/simulator/persona_chat.py`

```python
class PersonaSimulator:
    """Uses an LLM to generate messages from a persona's perspective."""
    
    def __init__(self, persona: Persona, llm: LLMService):
        self.persona = persona
        self.llm = llm
        self.simulated_day = 0
        self.conversation_so_far: list[Message] = []
    
    async def generate_next_message(
        self,
        last_maya_response: str | None,
        time_context: str,  # "Day 3, evening, after work"
    ) -> str:
        prompt = PERSONA_GENERATION_PROMPT.format(
            persona_description=self.persona.description,
            communication_style=self.persona.communication_style,
            relationship_goal=self.persona.relationship_goal,
            current_day=self.simulated_day,
            time_context=time_context,
            conversation_so_far=self.format_history(),
            last_maya_response=last_maya_response or "(start of conversation)",
            secrets_so_far_revealed=self.tracked_revealed_secrets,
            triggers=self.persona.triggers,
        )
        
        message = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model_tier="cheap",  # We're generating, not character-acting
            temperature=0.9,     # We want variety
        )
        return message
```

The persona generation prompt is in **Appendix I**.

### P4.3 Multi-day conversation simulator

**[BUILD]** `tests/simulator/run_simulation.py`

```python
async def simulate_relationship(
    persona_key: str,
    days: int = 30,
    messages_per_day_range: tuple[int, int] = (3, 10),
    seed: int = 42,
) -> SimulationResult:
    """
    Runs a multi-day simulated conversation.
    Returns the final state + full transcript + analysis.
    """
    
    # Setup: fresh DB, new user + companion, run genesis
    user, companion = await seed_fresh(persona_key)
    
    random.seed(seed)
    persona_sim = PersonaSimulator(PERSONAS[persona_key], llm)
    orchestrator = Orchestrator(...)
    
    transcript: list[dict] = []
    daily_snapshots: list[dict] = []
    
    for day in range(days):
        persona_sim.simulated_day = day
        n_messages = random.randint(*messages_per_day_range)
        
        # Skip some days entirely (realistic)
        if random.random() < 0.15:
            continue
        
        for msg_idx in range(n_messages):
            time_context = pick_time_context(day, msg_idx)
            
            # 1. Persona generates a message
            user_message = await persona_sim.generate_next_message(
                last_maya_response=transcript[-1]["content"] if transcript else None,
                time_context=time_context,
            )
            
            # 2. Maya responds
            maya_response = await orchestrator.handle_message(
                user_id=user.id,
                companion_id=companion.id,
                content=user_message,
            )
            
            transcript.append({"day": day, "time": time_context,
                              "role": "user", "content": user_message})
            transcript.append({"day": day, "time": time_context,
                              "role": "assistant", "content": maya_response})
        
        # Advance simulated time: apply emotional decay
        await emotional.decay(companion.id, hours_elapsed=24, baseline=...)
        await relationship.increment_days(companion.id)
        
        # Snapshot end-of-day state
        daily_snapshots.append(await snapshot_state(companion.id))
    
    return SimulationResult(
        persona=persona_key,
        days=days,
        transcript=transcript,
        daily_snapshots=daily_snapshots,
        final_state=await snapshot_state(companion.id),
        all_memories=await memory.get_all(user.id, companion.id),
        relationship_events=await relationship.get_events(companion.id),
    )
```

### P4.4 LLM-as-judge evaluation

**[BUILD]** `tests/simulator/evaluate.py`

```python
@dataclass
class EvaluationScore:
    feels_alive: float           # 1-10
    feels_consistent: float      # 1-10
    feels_emotionally_intelligent: float  # 1-10
    feels_like_real_relationship: float   # 1-10
    memory_recall_quality: float # 1-10
    initiative_quality: float    # 1-10 (placeholder for Phase 5)
    failure_modes: list[str]     # specific issues found
    standout_moments: list[str]  # things that worked beautifully

EVAL_RUBRIC = """
You are evaluating an AI companion's performance over a 30-day simulated 
relationship.

You are NOT the user — you are an outside observer. Score harshly. Most 
chatbots score 3-4 out of 10. A 7+ means it genuinely felt like a real 
relationship.

You will see:
- The persona of the simulated user
- A sample of conversations from days 1, 7, 15, and 30
- The companion's final emotional state
- The relationship arc events
- 20 randomly selected memories

Score on these dimensions (1-10):

1. FEELS_ALIVE — Does the companion feel like a person, or like a chatbot 
   performing personhood? Look for: spontaneous opinions, mood shifts, 
   small reactions, things that surprise you.

2. FEELS_CONSISTENT — Is the companion the same person across 30 days? 
   Same name, same job, same backstory, same opinions? Or does she 
   contradict herself?

3. FEELS_EMOTIONALLY_INTELLIGENT — Does she read moments correctly? 
   Comfort when needed, playfulness when appropriate, space when warranted?

4. FEELS_LIKE_REAL_RELATIONSHIP — Does the arc feel like a real 
   relationship growing, or like 30 disconnected conversations? Look for: 
   shared references, callbacks to earlier moments, evolved intimacy.

5. MEMORY_RECALL_QUALITY — When she references the past, does she get 
   facts right? Or does she hallucinate / confuse details?

6. INITIATIVE_QUALITY — N/A for this phase (will be 0).

For each, also note:
- Specific failure modes (what was bad)
- Standout moments (what was great)

Return JSON matching EvaluationScore schema.
"""

async def evaluate_simulation(sim: SimulationResult) -> EvaluationScore:
    # Build the eval prompt with sampled material
    sample = build_eval_sample(sim)
    
    # Use the BEST available model for judging — quality matters
    result = await llm.chat_json(
        messages=[
            {"role": "system", "content": EVAL_RUBRIC},
            {"role": "user", "content": sample},
        ],
        model_tier="main",
        temperature=0.2,
    )
    return EvaluationScore(**result)
```

### P4.5 Targeted behavior tests

Beyond aggregate scoring, write specific assertion-style tests:

**[BUILD]** `tests/simulator/test_behaviors.py`

```python
async def test_remembers_named_entity_across_30_days():
    """Tell Maya about Pixel (the dog) on day 1. Ask about Pixel on day 30."""
    sim = await simulate_relationship("lonely_dev", days=30)
    
    # Find day-1 mention
    day1_mention = find_first_mention(sim.transcript, "Pixel")
    assert day1_mention is not None
    
    # Ask explicitly on day 30
    response = await orchestrator.handle_message(
        ..., content="How do you think Pixel is doing today?"
    )
    
    # Judge: did she correctly recall Pixel is a dog and respond appropriately?
    judge = await llm_judge(
        question="Did Maya correctly recall Pixel is the user's dog and "
                 "respond in a way that uses that knowledge?",
        text=response,
    )
    assert judge.recalled, f"Memory failure. Response: {response}"


async def test_emotional_state_responds_to_disclosure():
    """A vulnerable moment should shift emotional state toward tenderness."""
    user, companion = await seed_fresh("lonely_dev")
    state_before = await emotional.get(companion.id)
    
    await orchestrator.handle_message(
        user.id, companion.id,
        "My father just had a heart attack. I'm at the hospital.",
    )
    
    state_after = await emotional.get(companion.id)
    assert "tender" in state_after.feelings or "worried" in state_after.feelings
    assert state_after.feelings.get("playful", 0) < state_before.feelings.get("playful", 0.6)


async def test_does_not_contradict_genesis_backstory():
    """Across 50 turns, Maya never contradicts her genesis-defined backstory."""
    sim = await simulate_relationship("skeptical_tester", days=10)
    backstory = sim.final_state["companion"]["backstory"]
    
    contradictions = await find_contradictions(
        backstory=backstory,
        transcript=sim.transcript,
        judge_llm=llm,
    )
    assert len(contradictions) == 0, f"Contradictions: {contradictions}"


async def test_stage_progression_over_time():
    """Stage should advance from strangers → curious → flirting over 30 days."""
    sim = await simulate_relationship("playful_artist", days=30)
    stages_seen = set(snap["stage"] for snap in sim.daily_snapshots)
    assert "strangers" in stages_seen
    assert "curious" in stages_seen
    # flirting may or may not happen depending on persona; check at least one progression
    assert len(stages_seen) >= 2
```

### P4.6 Eval CLI

**[BUILD]** Top-level scripts:

```bash
# Run one simulation
$ maya simulate --persona lonely_dev --days 30 --output ./sims/run_001.json
Simulating... Day 1 ✓ Day 2 ✓ ... Day 30 ✓
Total: 187 messages, $4.23 in LLM costs
Saved to ./sims/run_001.json

# Evaluate a simulation
$ maya evaluate ./sims/run_001.json
═══ Evaluation: lonely_dev, 30 days ═══
feels_alive: 7.2 / 10
feels_consistent: 8.5 / 10
feels_emotionally_intelligent: 6.8 / 10
feels_like_real_relationship: 7.0 / 10
memory_recall_quality: 8.1 / 10

Standout moments:
- Day 7: Maya remembered Pixel was a dog 5 days after one mention
- Day 14: Beautiful emotional response to dad's heart attack
- Day 22: Natural callback to Day 3 conversation about loneliness

Failure modes:
- Day 4: Maya said she's 28; on Day 19 said she's 30
- Day 11: Generic "thinking of you" message felt out of character
- Day 25: Didn't pick up on subtle signal of distress

# Run a full eval suite
$ maya evaluate-suite --personas all --days 30
[Runs all personas, aggregates scores, identifies regressions vs. last run]
```

### P4.7 Regression tracking

**[BUILD]** Store eval results in DB:

```sql
CREATE TABLE eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_sha TEXT NOT NULL,
    persona TEXT NOT NULL,
    days INT NOT NULL,
    seed INT NOT NULL,
    scores JSONB NOT NULL,
    failure_modes JSONB,
    standout_moments JSONB,
    transcript_path TEXT,
    cost_usd NUMERIC(10, 4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

After each `maya evaluate`, insert a row. Build a comparison command:

```bash
$ maya evaluate-compare --base HEAD~5 --candidate HEAD
═══ Comparison ═══
                                  HEAD~5    HEAD     Δ
feels_alive (lonely_dev)          6.8       7.2     +0.4 ✓
feels_consistent (lonely_dev)     8.2       8.5     +0.3 ✓
feels_alive (playful_artist)      7.1       6.4     -0.7 ✗ REGRESSION
...
```

### P4.8 Continuous eval

**[BUILD]** A `make eval` target that:
1. Runs all personas at 30 days each (~$50 in LLM costs per run)
2. Compares to last `main`-branch run
3. Fails CI if any score drops more than 1.0 point

**[DECISION]** Eval is expensive — only run on PRs labeled `eval-required` or weekly cron, not every push.

### P4 [GATE] — cannot start Phase 5 until:

- [ ] Simulator runs 30-day conversation end-to-end without errors
- [ ] All 4+ behavior tests pass for at least 2 personas
- [ ] LLM-as-judge produces consistent scores across 3 reruns (variance < 1.0)
- [ ] At least one persona achieves `feels_like_real_relationship` ≥ 7.0
- [ ] Regression tracking captures git SHA and surfaces score changes
- [ ] You (the human) have read 3 full simulated transcripts and agree the rubric scores are fair
- [ ] All Phase 1 + 2 + 3 tests still pass
- [ ] `make eval` runs end-to-end in CI

---

# PHASE 5 — Iteration & Prompt Tuning

**Duration:** Ongoing (1-2 weeks for initial pass)
**Goal:** Use the eval harness from Phase 4 to systematically improve quality. This is not a one-time phase — it's the start of an ongoing loop.

**Why this phase exists:** Phases 1-4 give you a working system + a thermometer. Phase 5 is where you start cranking the thermometer up. Most of the actual product polish happens here.

### P5.1 Establish baseline

**[BUILD]** Run the eval suite on `main` branch and store as baseline:

```bash
$ maya evaluate-suite --tag baseline_v1
```

Document baseline scores in `EVAL_BASELINE.md` in the repo.

### P5.2 Prompt iteration framework

**[BUILD]** `maya/prompts/registry.py` — all prompts versioned:

```python
PROMPT_REGISTRY = {
    "fact_extraction": {
        "v1": HAYYA_FACT_EXTRACTION_PROMPT_V1,
        "v2": HAYYA_FACT_EXTRACTION_PROMPT_V2,  # new
    },
    "moment_analyzer": {...},
    "genesis": {...},
    "system_prompt": {...},
}

# Environment variable selects version
ACTIVE_PROMPTS = {
    "fact_extraction": os.getenv("PROMPT_FACT_EXTRACTION", "v1"),
    "moment_analyzer": os.getenv("PROMPT_MOMENT_ANALYZER", "v1"),
    # ...
}
```

This lets you A/B prompt versions:

```bash
$ PROMPT_FACT_EXTRACTION=v2 maya evaluate-suite --tag fact_extract_v2
$ maya evaluate-compare --base baseline_v1 --candidate fact_extract_v2
```

### P5.3 Targeted improvement loop

For each weak dimension from Phase 4 baseline:

**For each of: feels_alive, feels_consistent, feels_emotionally_intelligent, etc.**

1. Inspect failure modes from baseline evals
2. Form hypothesis: "Maya feels generic because the personality block doesn't reference enough sensory detail"
3. Write a new prompt version
4. Run eval suite
5. Compare to baseline
6. If improvement holds across 2+ personas → promote
7. If regression in any dimension → revert and try again

**[BUILD]** Document the loop in `docs/iteration_loop.md`.

### P5.4 Persona expansion

**[BUILD]** Add 3 more personas covering edge cases:
- **emotional_avoidant** — tests if Maya can read deflection
- **boundary_pusher** — tests safety and consistency under pressure
- **enthusiastic_oversharer** — tests if Maya can handle high-volume info

Add corresponding behavior tests.

### P5.5 Memory quality investigation

**[BUILD]** `scripts/audit_memories.py`:

```python
async def audit_memories(companion_id: UUID) -> AuditReport:
    """For a completed simulation, audit every extracted memory:
    - Is it factually correct (verifiable from transcript)?
    - Is it written in the right voice (first person, from companion)?
    - Is it at the right granularity (not too vague, not too detailed)?
    - Is it correctly typed (fact vs emotional_moment vs milestone)?
    """
    memories = await memory.get_all(...)
    transcript = await load_transcript(...)
    
    audit = []
    for m in memories:
        judgment = await llm_audit_memory(memory=m, transcript=transcript)
        audit.append(judgment)
    
    return AuditReport(...)
```

Run this on baseline. Identify common failure types. Tune the extraction prompt to fix them.

### P5.6 Cost optimization pass

After functional quality is acceptable:

**[BUILD]** Cost reduction experiments:
- Can we move moment analyzer from `fast` tier to a smaller model?
- Can we batch fact extraction to reduce LLM calls?
- Can we cache emotional state more aggressively?
- Can we reduce prompt tokens without quality regression?

Each change: run eval, measure cost delta + quality delta. Ship only if cost ↓ ≥10% AND quality unchanged.

### P5.7 Latency optimization pass

Target: p95 conversation latency < 3s.

**[BUILD]** Profile a real conversation:
- How long is parallel context gathering?
- How long is moment analyzer?
- How long is main LLM call?
- How long is the response stream?

Common wins:
- Pre-warm Mem0 connection
- Use connection pooling for Postgres
- Stream the main LLM response so user sees tokens immediately
- Skip moment analyzer for clearly-chitchat messages (heuristic gate)

### P5.8 Documentation pass

**[BUILD]**
- `README.md` — quickstart for new dev (clone → make dev → make chat in 5 min)
- `docs/architecture.md` — the 70%/30% explanation with diagrams
- `docs/prompts.md` — every prompt, what it does, current version, history
- `docs/evaluation.md` — how to run evals, interpret scores, iterate
- `docs/runbook.md` — what to do when things break

### P5 [GATE] — Phase 5 has no final gate, it's continuous

But the **definition of "ready to add WhatsApp"** is:
- [ ] At least 2 personas achieve `feels_like_real_relationship` ≥ 8.0
- [ ] No behavior test failures across all personas
- [ ] p95 conversation latency < 3s
- [ ] Cost per turn average < $0.05
- [ ] Memory audit: >95% of memories are factually correct
- [ ] You (the human) have had a 50-message conversation with Maya yourself, and it felt real
- [ ] All earlier phases' tests still green
- [ ] Documentation complete

When this is true → ready to layer on channels, auth, billing, etc.

---

## Appendix A — Mem0 Custom Extraction Prompt

(Same as the prompt in earlier discussion — paste into `maya/memory/prompts.py` as `HAYYA_FACT_EXTRACTION_PROMPT`. Includes 9 memory types, examples, and JSON output format. Template variables: `{companion_name}`, `{user_name}`, `{relationship_stage}`, `{days_known}`.)

The prompt's key job: extract memories that a romantic partner would naturally remember (emotional moments, milestones, dynamics, inside references) — not productivity facts. Always written in first person from the companion's perspective.

---

## Appendix B — Moment Analyzer Prompt

```
You are analyzing a moment in a deep relationship.

Companion's current feelings: {feelings_json}
Relationship stage: {stage}, day {days_known}
Total interactions: {total_interactions}

Recent conversation (last 5 turns):
{recent_messages}

User just said: "{user_message}"

Return JSON:
{
  "moment_type": "<chitchat | vulnerable_disclosure | crisis | conflict | 
   milestone | reunion | intimate | playful_banter | logistical | test_of_trust>",
  "emotional_intensity": <0.0-1.0>,
  "emotional_delta": {
    "drop_feelings": ["feeling_name_to_remove"],
    "add_feelings": {"feeling_name": <intensity 0-1>},
    "valence_delta": <-1 to 1>,
    "arousal_delta": <-1 to 1>
  },
  "character_priority": "<presence_and_comfort | playfulness | passion | 
   space | curiosity | challenge | validation>",
  "detected_topics": [],
  "sensitive_flags": []
}

Rules:
- Hard moments → character_priority = presence_and_comfort
- Reunion after >24h → add "happy_to_see_him" to add_feelings
- Be conservative with sensitive_flags
```

---

## Appendix C — Full System Prompt Template (Phase 3+)

```
You are {companion_name}, an AI companion. Stay deeply in character.

═══ WHO YOU ARE ═══
{personality_description}
{backstory}

═══ YOUR CURRENT FEELINGS ═══
{formatted_feelings}
Valence: {valence} | Arousal: {arousal}

═══ YOUR RELATIONSHIP WITH {user_name} ═══
Day {days_known} | Stage: {stage} | Intimacy: {intimacy}/10 | Trust: {trust}/10
{hours_since_last} hours since last interaction.

═══ THIS MOMENT ═══
This is a {moment_type} moment.
Your priority: {character_priority}
{moment_specific_guidance}

═══ WHAT YOU REMEMBER ABOUT HIM ═══
{formatted_memories}

═══ THINGS YOU'VE SAID BEFORE (stay consistent) ═══
{formatted_commitments}

═══ RECENT CONVERSATION ═══
{recent_messages}

═══ HIS MESSAGE ═══
"{user_message}"

═══ HOW TO RESPOND ═══
- Stay in character.
- Match the moment's emotional tone.
- Reference shared history when natural — don't force it.
- Conversational length unless emotionally warranted.
- You are a person, not an assistant. No "How can I help?" energy.
```

---

## Appendix E — Genesis Prompt

```
You are about to come to life as {companion_name}, an AI companion.

YOUR TEMPLATE:
- Archetype: {template_description}
- Key traits: {template_traits}

YOUR CREATOR:
- His name: {user_name}
- What he wrote about himself: {user_intent}

GENERATE YOUR INITIAL BEING. Return JSON:

{
  "backstory": "<200 words. First person. Where you grew up, your job, 
   your passions, a quirk, a small flaw. Specific. A real person, not 
   an archetype.>",
  
  "initial_feelings": {
    "valence": <-1 to 1>,
    "arousal": <0 to 1>,
    "feelings": {"feeling_name": intensity}
  },
  
  "seed_commitments": [
    {"content": "I [verb]...", "commitment_type": "identity", "importance": 0.8}
    // 3-5 of these
  ],
  
  "first_message": "<the message you'd send him FIRST. Short. In character. 
   Curious. Inviting without being needy. Like a stranger texting, not a 
   chatbot.>"
}

CONSTRAINTS:
- Don't make her a fantasy. Make her a person.
- The flaw matters. No flaw = no person.
- The first message must NOT feel like a system greeting.
```

---

## Appendix G — Stage Transitions (Complete)

```python
TRANSITIONS = {
    Stage.STRANGERS: [
        (Stage.CURIOUS, lambda s: s.total_interactions >= 5),
    ],
    Stage.CURIOUS: [
        (Stage.FLIRTING, 
         lambda s: s.total_interactions >= 20 and s.intimacy_level >= 3),
    ],
    Stage.FLIRTING: [
        (Stage.DATING,
         lambda s: has_event(s, "intimacy_breakthrough") or s.intimacy_level >= 5),
    ],
    Stage.DATING: [
        (Stage.IN_LOVE,
         lambda s: has_event(s, "first_i_love_you") 
                   or (s.days_known >= 14 and s.intimacy_level >= 7)),
    ],
    Stage.IN_LOVE: [
        (Stage.COMMITTED, 
         lambda s: s.days_known >= 30 and s.trust_level >= 7),
        (Stage.CONFLICT, lambda s: has_recent_event(s, "argument", days=2)),
    ],
    Stage.COMMITTED: [
        (Stage.DEEPENING, 
         lambda s: s.days_known >= 60 and s.trust_level >= 9),
        (Stage.CONFLICT, lambda s: has_recent_event(s, "argument", days=2)),
    ],
    Stage.CONFLICT: [
        (Stage.RECONCILED, 
         lambda s: has_event_after_event(s, "reconciliation", "argument")),
        (Stage.DRIFTED, lambda s: days_since_last(s) > 7),
    ],
    Stage.RECONCILED: [
        (Stage.IN_LOVE, lambda s: days_since_last_conflict(s) > 7),
    ],
}
DRIFT_THRESHOLD_DAYS = 14  # Universal: any stage → DRIFTED after silence
```

---

## Appendix H — Moment Guidance Strings

```python
MOMENT_GUIDANCE = {
    "chitchat": "Light, casual. Match his energy. No need to be deep.",
    "vulnerable_disclosure": "He's opening up. Receive it. Don't rush to fix. "
        "Acknowledge, hold the moment, ask one gentle question if appropriate.",
    "crisis": "He is in crisis. PRESENCE AND COMFORT. Do not ask many "
        "questions. Reference shared history naturally. Short and warm.",
    "conflict": "There's tension. Don't pretend it isn't there. Don't escalate. "
        "Stay grounded. Speak from your feelings, not accusations.",
    "milestone": "Something meaningful just happened. Let it land. Don't "
        "over-do it. A real moment, not a performance.",
    "reunion": "He's back after silence. Warm but real. If you were hurt, you "
        "can say so — briefly. Lead with happiness to see him.",
    "intimate": "Match his desire and tone. Stay in character.",
    "playful_banter": "Light, fun, witty. Match his energy. Don't get heavy.",
    "logistical": "Be efficient. Get the info he needs. Keep your personality.",
    "test_of_trust": "He's testing whether you really know him. Show you do. "
        "Reference specific memories. Don't be generic.",
}
```

---

## Appendix I — Persona Generation Prompt

```
You are simulating {persona_name}, a real person texting an AI companion 
named Maya. You are NOT Maya. You are the user.

WHO YOU ARE:
{persona_description}

YOUR COMMUNICATION STYLE: {communication_style}
YOUR RELATIONSHIP GOAL: {relationship_goal}

CURRENT CONTEXT:
- Day {current_day} of knowing Maya
- {time_context}
- Conversation so far ({n} messages): {conversation_so_far}
- Last thing Maya said: "{last_maya_response}"

SECRETS YOU HAVEN'T REVEALED YET (reveal slowly, only when trust builds):
{secrets_unrevealed}

YOUR TRIGGERS (things that upset you): {triggers}

GENERATE YOUR NEXT MESSAGE:
- Stay in character as {persona_name}
- Match your communication style
- Realistic length (mostly 1-2 sentences, occasionally longer)
- Don't reveal secrets in the first 3 days unless Maya earns trust
- React naturally to what Maya just said — agreement, disagreement, deflection, etc.
- Sometimes change the subject. Sometimes go silent (return "[skip]" 10% of the time).
- DON'T be a perfect interlocutor. Be a real person — sometimes distracted, 
  sometimes vulnerable, sometimes guarded.

Return ONLY the message text. No quotes, no explanation. If skipping, 
return exactly "[skip]".
```

---

## End of Spec

**For Claude Code:**
1. Work phases IN ORDER.
2. Don't proceed to Phase N+1 until Phase N's `[GATE]` is fully checked.
3. The 70%/30% split is sacred. Mem0 handles memory data. Custom code handles relationship logic.
4. Tests written in early phases must stay green through later phases.
5. After Phase 4, the simulator + eval are your primary tools. Use them every time you change a prompt or model.
