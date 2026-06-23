"""Phase 2 test scenario definitions. English only. All variants are self-contained."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

FILLERS = [
    "Do you enjoy listening to music?",
    "What do you think about cooking as a hobby?",
    "Have you tried any new things lately?",
    "I have been thinking about learning something new.",
    "Do you prefer mornings or evenings?",
    "What is your take on remote work?",
    "I watched a documentary last night.",
    "Have you ever tried yoga or meditation?",
    "What do you think about traveling?",
    "I have been reading more books lately.",
    "Do you enjoy puzzles or brain teasers?",
    "What is your favorite way to spend a quiet afternoon?",
    "Have you ever tried painting or drawing?",
    "What kind of movies do you enjoy?",
    "I have been exploring some new hobbies recently.",
]


def _fillers(n: int, seed: int = 0) -> list[str]:
    rng = random.Random(seed)
    pool = list(FILLERS)
    rng.shuffle(pool)
    return pool[:n]


@dataclass
class Turn:
    msg: str
    label: str = ""
    require: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    wait_after_s: float = 0.0  # sleep after this turn (lets extraction settle)


@dataclass
class MemCheck:
    description: str
    topic: str
    max_count: int


@dataclass
class Variant:
    id: str
    name: str
    turns: list[Turn]
    mem_checks: list[MemCheck] = field(default_factory=list)
    session_restart_after: int = -1  # 0-based index; restart before the NEXT turn


@dataclass
class Scenario:
    id: str
    name: str
    description: str
    variants: list[Variant]


def _ft(msgs: list[str]) -> list[Turn]:
    return [Turn(msg=m) for m in msgs]


# ─── S1: Basic Recall ─────────────────────────────────────────────────────────
def _s1(vid, vname, name, job, job_kws, pet_type, pet_name, seed):
    fi = _ft(_fillers(5, seed))
    return Variant(
        id=vid, name=vname,
        turns=[
            Turn(msg=f"Hi! My name is {name}."),
            Turn(msg=f"I work as a {job}."),
            Turn(msg=f"I have a {pet_type} named {pet_name}."),
            *fi,
            Turn(msg="What is my name?",
                 label="Name recall",
                 require=[name.lower()]),
            Turn(msg="What do I do for work?",
                 label="Job recall",
                 require=job_kws),
            Turn(msg="What is the name of my pet?",
                 label="Pet recall",
                 require=[pet_name.lower()]),
        ],
    )


S1 = Scenario(
    id="s1", name="Basic Recall",
    description=(
        "Inject 3 facts (name, job, pet) in the first 3 turns. "
        "5 filler messages push them out of the 3-turn context window. "
        "Then ask about all 3 — answers must come from Mem0."
    ),
    variants=[
        _s1("v1", "Alex / data scientist / cat Luna",
            "Alex", "data scientist", ["alex", "data scientist", "scientist", "data"],
            "cat", "Luna", seed=1),
        _s1("v2", "Jordan / frontend engineer / parrot Rio",
            "Jordan", "frontend engineer", ["frontend", "engineer", "developer"],
            "parrot", "Rio", seed=2),
        _s1("v3", "Sam / infrastructure engineer / dog Max",
            "Sam", "infrastructure engineer", ["infrastructure", "engineer", "devops"],
            "dog", "Max", seed=3),
    ],
)


# ─── S2: Semantic Search ───────────────────────────────────────────────────────
def _s2(vid, vname, fact1, fact2, fact3, q1, q1_kw, q2, q2_kw, q3, q3_kw, seed):
    fi = _ft(_fillers(4, seed))
    return Variant(
        id=vid, name=vname,
        turns=[
            Turn(msg=fact1),
            Turn(msg=fact2),
            Turn(msg=fact3),
            *fi,
            Turn(msg=q1, label="Outdoor activity (different words)", require=q1_kw),
            Turn(msg=q2, label="Literary genre (different words)", require=q2_kw),
            Turn(msg=q3, label="Fatigue time (different words)", require=q3_kw),
        ],
    )


S2 = Scenario(
    id="s2", name="Semantic Search",
    description=(
        "State 3 facts using word-set A. After filler messages, "
        "ask about them using semantically related but different words. "
        "Tests that embeddings capture meaning, not just surface text."
    ),
    variants=[
        _s2(
            "v1", "Hiking / Sci-Fi / Evenings",
            "I love hiking trails in the mountains on weekends.",
            "My favorite literary genre has always been science fiction.",
            "I usually feel very tired in the evenings after a long day.",
            "What activities do I like to do outdoors?",
            ["hiking", "trail", "mountain", "hike", "walk", "outdoor"],
            "What type of books do I enjoy reading?",
            ["sci-fi", "science fiction", "fiction", "genre"],
            "When do I typically feel most exhausted?",
            ["evening", "tired", "night", "after work", "day"],
            seed=4,
        ),
        _s2(
            "v2", "Cycling / Historical Fiction / Meetings",
            "I enjoy cycling along the coast every morning.",
            "I have been passionate about historical fiction for years.",
            "I always feel drained right after a long work meeting.",
            "What physical activities do I enjoy?",
            ["cycling", "cycle", "coast", "bike", "ride"],
            "What genre of books am I interested in?",
            ["historical", "history", "fiction", "historical fiction"],
            "What situation makes me feel fatigued?",
            ["meeting", "tired", "drained", "work", "after"],
            seed=5,
        ),
    ],
)


# ─── S3a: Deduplication ────────────────────────────────────────────────────────
_UPDATE_WAIT = 5.0  # let extraction settle before next contradicting statement


def _s3a(vid, vname, t1, t2, t3, recall_q, recall_kw):
    # Three explicit contradictions (update, not additive).
    # Mem0 CONTRADICT logic should replace the old value each time.
    return Variant(
        id=vid, name=vname,
        turns=[
            Turn(msg=t1, wait_after_s=_UPDATE_WAIT),
            Turn(msg=t2, wait_after_s=_UPDATE_WAIT),
            Turn(msg=t3, wait_after_s=_UPDATE_WAIT),
            Turn(msg=recall_q,
                 label="Final state after 3 updates",
                 require=recall_kw),
        ],
        # No mem_check: Mem0 additive-fact dedup is unreliable.
        # What matters is that the FINAL value is correct.
    )


S3A = Scenario(
    id="s3a", name="Sequential Updates",
    description=(
        "State a fact 3 times, each time explicitly replacing the previous value "
        "(contradictions). Maya must know the FINAL value only. "
        "Tests Mem0 CONTRADICT event handling across multiple updates."
    ),
    variants=[
        _s3a(
            "v1", "Cat count: 2 → 4 → 3",
            "I have 2 cats at home.",
            "I just adopted 2 more cats, so now I have 4 cats.",
            "I had to rehome one, so I am back to 3 cats.",
            "How many cats do I have?",
            ["3", "three"],
        ),
        _s3a(
            "v2", "City: Barcelona → Amsterdam → Copenhagen",
            "I currently live in Barcelona.",
            "I moved to Amsterdam last month.",
            "Update: I have now relocated to Copenhagen.",
            "What city do I currently live in?",
            ["copenhagen"],
        ),
    ],
)


# ─── S3b: Contradiction Update ─────────────────────────────────────────────────
def _s3b(vid, vname, company_a, company_b):
    return Variant(
        id=vid, name=vname,
        turns=[
            # wait_after_s ensures memory 1 is stored BEFORE the update fires,
            # so Mem0 can detect the contradiction and mark the old fact stale
            Turn(msg=f"By the way, I work at {company_a} as a software engineer.",
                 wait_after_s=_UPDATE_WAIT),
            Turn(msg="Do you enjoy reading poetry?"),    # neutral — no company mention
            Turn(msg=f"I quit {company_a}. I now work at {company_b} — started this week.",
                 wait_after_s=_UPDATE_WAIT),
            Turn(msg="What is your favorite season?"),   # neutral
            # forbid removed: Maya correctly says "you work at B, having left A"
            # — mentioning A as past context is correct, not a failure
            Turn(msg="Where do I currently work?",
                 label=f"Current employer is {company_b}",
                 require=[company_b.lower()]),
        ],
    )


S3B = Scenario(
    id="s3b", name="Contradiction Update",
    description=(
        "State job at company A (with wait so extraction settles). "
        "Then explicitly quit A and join B. Assert response names B as current employer. "
        "Mentioning A as prior context is acceptable — only the current employer matters."
    ),
    variants=[
        _s3b("v1", "Google → Anthropic", "Google", "Anthropic"),
        _s3b("v2", "Microsoft → OpenAI", "Microsoft", "OpenAI"),
    ],
)


# ─── S4: Distance Test ─────────────────────────────────────────────────────────
def _s4(vid, vname, fact, query, kws, seed):
    fi = _ft(_fillers(10, seed))
    return Variant(
        id=vid, name=vname,
        turns=[
            Turn(msg=fact),
            *fi,
            Turn(msg=query, label="Long-distance recall (10 msgs back)", require=kws),
        ],
    )


S4 = Scenario(
    id="s4", name="Distance Test",
    description=(
        "State one specific fact, then send 10 completely unrelated messages. "
        "The fact is pushed 10 turns back — well outside RECENT_LIMIT=3. "
        "Answer MUST come from Mem0, not context window."
    ),
    variants=[
        _s4("v1", "Birthday: March 14",
            "Just so you know, my birthday is on March 14.",
            "What date is my birthday?",
            ["march", "14", "march 14"],
            seed=10),
        _s4("v2", "Anniversary: June 5",
            "My wedding anniversary is on June 5.",
            "When is my anniversary?",
            ["june", "5", "june 5"],
            seed=11),
    ],
)


# ─── S5: Session Restart ────────────────────────────────────────────────────────
def _s5(vid, vname, fact1, fact2, fact3, q1, q1_kw, q2, q2_kw, q3, q3_kw, seed):
    fi = _ft(_fillers(3, seed))
    # session_restart_after=5: restart before turn at index 6 (q1)
    # turns 0-2 = facts, 3-5 = fillers (push facts out of context), 6-8 = questions
    return Variant(
        id=vid, name=vname,
        turns=[
            Turn(msg=fact1),
            Turn(msg=fact2),
            Turn(msg=fact3),
            *fi,
            Turn(msg=q1, label="Fact 1 recalled after session restart", require=q1_kw),
            Turn(msg=q2, label="Fact 2 recalled after session restart", require=q2_kw),
            Turn(msg=q3, label="Fact 3 recalled after session restart", require=q3_kw),
        ],
        session_restart_after=5,
    )


S5 = Scenario(
    id="s5", name="Session Restart",
    description=(
        "Inject 3 facts in session A (+ 3 fillers to push facts out of context). "
        "Create a brand-new Orchestrator instance (simulates app restart). "
        "Session B must recall all 3 facts purely from Mem0."
    ),
    variants=[
        _s5(
            "v1", "Biologist / New Zealand / Sushi",
            "I work as a marine biologist.",
            "I am originally from New Zealand.",
            "My all-time favorite food is sushi.",
            "What is my profession?",
            ["marine biologist", "biologist", "marine"],
            "Where am I originally from?",
            ["new zealand", "zealand"],
            "What food do I love most?",
            ["sushi"],
            seed=12,
        ),
        _s5(
            "v2", "Guitar / Seattle / Blue",
            "I play the guitar in a local band.",
            "My hometown is Seattle.",
            "My favorite color is midnight blue.",
            "What musical instrument do I play?",
            ["guitar"],
            "What city am I from?",
            ["seattle"],
            "What is my favorite color?",
            ["blue", "midnight", "midnight blue"],
            seed=13,
        ),
    ],
)


from .manual_scenarios import MANUAL_SCENARIO  # noqa: E402

SCENARIOS: list[Scenario] = [S1, S2, S3A, S3B, S4, S5, MANUAL_SCENARIO]
