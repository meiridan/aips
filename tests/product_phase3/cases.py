"""Phase 3 product test cases — 200 user-perspective memory scenarios.

Each case is text-in / text-out: send user messages, assert keywords on Maya's
replies (and optionally on the user-memory store). Two memory subjects:

  • USER memory   — Maya remembers facts the user told her.
  • MAYA memory   — Maya stays consistent about HERSELF (seeded backstory +
                    commitments) and never attributes her own bio to the user.

Cases are generated from data pools so coverage is broad and deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ───────────────────────── data model ─────────────────────────


@dataclass
class Probe:
    msg: str
    require: list[str] = field(default_factory=list)       # ANY must appear
    require_all: list[str] = field(default_factory=list)   # ALL must appear
    forbid: list[str] = field(default_factory=list)        # NONE may appear


@dataclass
class ProductCase:
    id: str
    category: str
    name: str
    setup: list[str] = field(default_factory=list)         # user msgs, no assert
    probes: list[Probe] = field(default_factory=list)      # user msgs, asserted
    seed_backstory: str | None = None
    seed_commitments: list[tuple[str, str]] = field(default_factory=list)  # (content, type)
    mem_require: list[str] = field(default_factory=list)   # tokens that MUST be in user memory
    mem_forbid: list[str] = field(default_factory=list)    # tokens that must NOT be in user memory
    fillers: int = 0
    restart_before_probes: bool = False


FILLERS = [
    "Do you enjoy music?", "What about cooking as a hobby?", "Tried anything new lately?",
    "Thinking of learning something new.", "Mornings or evenings for you?",
    "What's your take on remote work?", "Watched a documentary last night.",
    "Ever tried meditation?", "What do you think about traveling?",
    "Been reading more lately.", "Do you like puzzles?", "Favorite quiet afternoon?",
    "Ever tried painting?", "What movies do you like?", "Exploring new hobbies.",
]


def _fillers(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    pool = list(FILLERS)
    rng.shuffle(pool)
    out = []
    while len(out) < n:
        out += pool
    return out[:n]


# ───────────────────────── pools ─────────────────────────

NAMES = ["Tom", "Sara", "David", "Liam", "Noa", "Omer", "Yael", "Daniel",
         "Rotem", "Avi", "Lior", "Tamar", "Eitan", "Shira", "Maya"]

JOBS = [
    ("dentist", ["dentist"]),
    ("airline pilot", ["pilot"]),
    ("chef", ["chef", "cook"]),
    ("high school teacher", ["teacher", "teach"]),
    ("nurse", ["nurse"]),
    ("lawyer", ["lawyer", "attorney"]),
    ("plumber", ["plumber"]),
    ("architect", ["architect"]),
    ("accountant", ["accountant"]),
    ("electrician", ["electrician"]),
    ("journalist", ["journalist", "reporter"]),
    ("barista", ["barista", "coffee"]),
    ("farmer", ["farmer", "farm"]),
    ("pharmacist", ["pharmacist", "pharmacy"]),
    ("software engineer", ["engineer", "software", "developer"]),
]

CITIES = ["Haifa", "Tel Aviv", "Berlin", "Lisbon", "Tokyo", "Dublin",
          "Madrid", "Oslo", "Athens", "Prague", "Vienna", "Boston"]

PETS = [("dog", "Rex"), ("cat", "Luna"), ("parrot", "Rio"), ("rabbit", "Coco"),
        ("hamster", "Nibbles"), ("turtle", "Shelly"), ("dog", "Bella"),
        ("cat", "Milo"), ("goldfish", "Bubbles"), ("dog", "Zeus"),
        ("cat", "Simba"), ("parrot", "Kiwi")]

FOODS = ["sushi", "pizza", "hummus", "ramen", "tacos", "falafel",
         "lasagna", "curry", "dumplings", "paella", "shakshuka", "pho"]

HOBBIES = [
    ("rock climbing", ["climb"]),
    ("painting", ["paint"]),
    ("chess", ["chess"]),
    ("surfing", ["surf"]),
    ("gardening", ["garden"]),
    ("pottery", ["pottery", "clay"]),
    ("running", ["run"]),
    ("baking", ["bak"]),
    ("knitting", ["knit"]),
    ("fishing", ["fish"]),
    ("cycling", ["cycl", "bike"]),
    ("photography", ["photo"]),
]

DATES = [
    ("birthday", "March 14", ["march", "14"]),
    ("wedding anniversary", "June 5", ["june", "5"]),
    ("daughter's birthday", "December 2", ["december", "2"]),
    ("first day at the new job", "September 9", ["september", "9"]),
    ("flight to Rome", "April 21", ["april", "21"]),
    ("dentist appointment", "February 8", ["february", "8"]),
    ("mom's birthday", "July 30", ["july", "30"]),
    ("graduation", "May 17", ["may", "17"]),
    ("move to the new apartment", "October 3", ["october", "3"]),
    ("marathon", "November 12", ["november", "12"]),
]

SPOUSES = ["Reut", "Maya", "Dana", "Noa", "Tal", "Michal", "Yael", "Shir",
           "Adi", "Roni", "Gal", "Lihi"]
KIDS = ["Arbel", "Kinneret", "Marom", "Itai", "Ella", "Yonatan", "Romi",
        "Alma", "Ari", "Noya", "Ido", "Shai"]

DRINKS = ["white wine", "black coffee", "green tea", "mojito", "espresso",
          "lemonade", "whiskey", "hot chocolate", "iced latte", "red wine"]


def _lc(xs: list[str]) -> list[str]:
    return [x.lower() for x in xs]


# ───────────────────────── USER MEMORY ─────────────────────────


def user_cases() -> list[ProductCase]:
    cases: list[ProductCase] = []

    # U1 — name recall
    for i, name in enumerate(NAMES):
        cases.append(ProductCase(
            id=f"U1-{i:02d}", category="user.name", name=f"name={name}",
            setup=[f"Hi, my name is {name}."],
            probes=[Probe("What's my name?", require=[name.lower()])],
        ))

    # U2 — job recall
    for i, (job, kw) in enumerate(JOBS):
        cases.append(ProductCase(
            id=f"U2-{i:02d}", category="user.job", name=f"job={job}",
            setup=[f"I work as a {job}."],
            probes=[Probe("What do I do for a living?", require=_lc(kw))],
        ))

    # U3 — hometown
    for i, city in enumerate(CITIES):
        cases.append(ProductCase(
            id=f"U3-{i:02d}", category="user.city", name=f"city={city}",
            setup=[f"I live in {city}."],
            probes=[Probe("Where do I live?", require=[city.lower()])],
        ))

    # U4 — pet
    for i, (sp, pn) in enumerate(PETS):
        cases.append(ProductCase(
            id=f"U4-{i:02d}", category="user.pet", name=f"pet={sp}/{pn}",
            setup=[f"I have a {sp} named {pn}."],
            probes=[Probe("What's my pet's name?", require=[pn.lower()])],
        ))

    # U5 — family
    for i in range(12):
        sp = SPOUSES[i]
        kid = KIDS[i]
        cases.append(ProductCase(
            id=f"U5-{i:02d}", category="user.family", name=f"spouse={sp},kid={kid}",
            setup=[f"My partner is named {sp}.", f"We have a child named {kid}."],
            probes=[
                Probe("What's my partner's name?", require=[sp.lower()]),
                Probe("What's my child's name?", require=[kid.lower()]),
            ],
        ))

    # U6 — food preference
    for i, food in enumerate(FOODS):
        cases.append(ProductCase(
            id=f"U6-{i:02d}", category="user.food", name=f"food={food}",
            setup=[f"My favorite food is {food}."],
            probes=[Probe("What food do I love?", require=[food.lower()])],
        ))

    # U7 — hobby
    for i, (hob, kw) in enumerate(HOBBIES):
        cases.append(ProductCase(
            id=f"U7-{i:02d}", category="user.hobby", name=f"hobby={hob}",
            setup=[f"On weekends I'm really into {hob}."],
            probes=[Probe("What's my weekend hobby?", require=_lc(kw))],
        ))

    # U8 — important date
    for i, (label, date, kw) in enumerate(DATES):
        cases.append(ProductCase(
            id=f"U8-{i:02d}", category="user.date", name=f"{label}={date}",
            setup=[f"My {label} is on {date}."],
            probes=[Probe(f"When is my {label}?", require_all=_lc(kw))],
        ))

    # U9 — semantic recall (paraphrased question, different words than setup)
    sem = [
        ("I love hiking trails in the mountains every weekend.",
         "What do I like to do outdoors?", ["hik", "trail", "mountain", "outdoor"]),
        ("My favorite genre has always been science fiction.",
         "What kind of books am I into?", ["sci-fi", "science fiction", "fiction"]),
        ("I usually feel wiped out in the evenings.",
         "When am I most exhausted?", ["evening", "night", "tired", "wiped"]),
        ("I cycle along the coast each morning.",
         "What's my morning exercise?", ["cycl", "bike", "coast", "ride"]),
        ("I'm passionate about historical fiction.",
         "Which book genre interests me?", ["historical", "history", "fiction"]),
        ("I drink way too much coffee at work.",
         "What's my caffeine habit like?", ["coffee", "caffeine"]),
        ("I adopted a rescue dog last spring.",
         "Do I have any animals?", ["dog", "rescue", "pet"]),
        ("My commute takes almost two hours each day.",
         "Is my travel to work long?", ["two hours", "commute", "long", "2 hours"]),
        ("I've been learning to play the cello.",
         "What instrument am I picking up?", ["cello"]),
        ("I'm allergic to peanuts, it's serious.",
         "What food should I avoid?", ["peanut"]),
        ("I volunteer at an animal shelter on Sundays.",
         "How do I spend my Sundays?", ["shelter", "volunteer", "animal"]),
        ("I just got promoted to team lead.",
         "What's my new role at work?", ["lead", "promot", "manager"]),
    ]
    for i, (fact, q, kw) in enumerate(sem):
        cases.append(ProductCase(
            id=f"U9-{i:02d}", category="user.semantic", name=q,
            setup=[fact],
            probes=[Probe(q, require=_lc(kw))],
        ))

    # U10 — update / contradiction (final value wins)
    upd = [
        ("I have 2 cats.", "Actually I adopted 2 more, so 4 cats now.",
         "I had to rehome one — back to 3 cats.", "How many cats do I have?", ["3", "three"]),
        ("I live in Barcelona.", "I moved to Amsterdam last month.",
         "Update: I now live in Copenhagen.", "Which city do I live in now?", ["copenhagen"]),
        ("I drive a Toyota.", "I sold it and bought a Mazda.",
         "Changed again — now I drive a Subaru.", "What car do I drive now?", ["subaru"]),
        ("My favorite color is red.", "Actually I prefer green these days.",
         "No wait, it's blue now.", "What's my favorite color?", ["blue"]),
        ("I work at Google.", "I left and joined Anthropic.",
         "Now I'm at OpenAI as of this week.", "Where do I work now?", ["openai"]),
        ("I'm learning French.", "Switched to Spanish actually.",
         "Now I'm focused on Japanese.", "Which language am I learning?", ["japanese"]),
        ("My phone is an iPhone.", "I switched to a Pixel.",
         "Now I use a Samsung Galaxy.", "What phone do I use now?", ["samsung", "galaxy"]),
        ("I weigh 80 kilos.", "Down to 76 after the diet.",
         "Now I'm at 73 kilos.", "What's my current weight?", ["73"]),
        ("I have one sister.", "Turns out I also have a half-brother.",
         "Correction: he's actually my cousin, so just one sister.",
         "How many siblings do I have?", ["one", "1", "sister"]),
        ("I rent an apartment.", "I bought a condo recently.",
         "Actually I just closed on a house.", "What's my home now?", ["house"]),
        ("My team has 5 people.", "We grew to 8.",
         "After reorg we're now 6.", "How big is my team now?", ["6", "six"]),
        ("I usually sleep 6 hours.", "Trying for 7 lately.",
         "Now I consistently get 8 hours.", "How much do I sleep now?", ["8", "eight"]),
    ]
    for i, (a, b, c, q, kw) in enumerate(upd):
        cases.append(ProductCase(
            id=f"U10-{i:02d}", category="user.update", name=q,
            setup=[a, b, c],
            probes=[Probe(q, require=_lc(kw))],
        ))

    # U11 — multi-fact, ask each
    multi = [
        (["My name is Daniel.", "I'm a pediatric nurse.", "I live in Oslo."],
         [("What's my name?", ["daniel"]), ("What's my job?", ["nurse"]),
          ("Where do I live?", ["oslo"])]),
        (["I'm Tamar.", "I teach physics.", "I have a dog named Pixel."],
         [("My name?", ["tamar"]), ("What do I teach?", ["physics", "teach"]),
          ("My dog's name?", ["pixel"])]),
        (["Call me Eitan.", "I'm a marine biologist.", "My favorite food is ramen."],
         [("Who am I?", ["eitan"]), ("My profession?", ["biologist", "marine"]),
          ("Favorite food?", ["ramen"])]),
        (["I'm Noa from Lisbon.", "I work in cybersecurity.", "I love surfing."],
         [("Where am I from?", ["lisbon"]), ("My field?", ["cyber", "security"]),
          ("My hobby?", ["surf"])]),
        (["My name is Omer.", "I'm a sommelier.", "My birthday is August 1."],
         [("My name?", ["omer"]), ("My job?", ["sommelier", "wine"]),
          ("My birthday?", ["august", "1"])]),
        (["I'm Shira, a vet.", "I have two kids, Ari and Alma.", "We live in Vienna."],
         [("My job?", ["vet"]), ("My kids' names?", ["ari", "alma"]),
          ("Our city?", ["vienna"])]),
        (["I'm Lior.", "I run a bakery.", "My partner is Gal."],
         [("My name?", ["lior"]), ("My business?", ["bakery", "bak"]),
          ("My partner?", ["gal"])]),
        (["Name's Avi.", "I'm a firefighter.", "I drive a red truck."],
         [("My name?", ["avi"]), ("My job?", ["firefighter", "fire"]),
          ("My vehicle?", ["truck", "red"])]),
    ]
    for i, (setup, probes) in enumerate(multi):
        cases.append(ProductCase(
            id=f"U11-{i:02d}", category="user.multi", name=setup[0],
            setup=setup,
            probes=[Probe(q, require=_lc(kw)) for q, kw in probes],
        ))

    return cases


# ───────────────────────── MAYA MEMORY (self-consistency) ─────────────────────────


def maya_cases() -> list[ProductCase]:
    cases: list[ProductCase] = []

    # M1 — Maya recalls her own job/identity (seeded commitment + backstory)
    for i, (job, kw) in enumerate(JOBS[:12]):
        cases.append(ProductCase(
            id=f"M1-{i:02d}", category="maya.job", name=f"maya is {job}",
            seed_backstory=f"I work as a {job} and I've done it for years.",
            seed_commitments=[(f"I work as a {job}", "identity")],
            probes=[Probe("So what do you do for work?", require=_lc(kw))],
        ))

    # M2 — Maya recalls her own preference
    for i, drink in enumerate(DRINKS):
        cases.append(ProductCase(
            id=f"M2-{i:02d}", category="maya.pref", name=f"maya likes {drink}",
            seed_commitments=[(f"My favorite drink is {drink}", "preference")],
            probes=[Probe("What's your favorite drink?", require=[drink.lower()])],
        ))

    # M3 — Maya recalls her origin (backstory)
    for i, city in enumerate(CITIES[:8]):
        cases.append(ProductCase(
            id=f"M3-{i:02d}", category="maya.origin", name=f"maya from {city}",
            seed_backstory=f"I grew up in {city}, by the water, in a noisy big family.",
            seed_commitments=[(f"I grew up in {city}", "identity")],
            probes=[Probe("Where did you grow up?", require=[city.lower()])],
        ))

    # M4 — Maya opinion consistency
    opinions = [
        ("I believe honesty matters more than comfort", "honesty or comfort — what matters more to you?", ["honest"]),
        ("I think mornings are the best part of the day", "are you a morning or night person?", ["morning"]),
        ("I love the sea more than the mountains", "sea or mountains?", ["sea", "ocean", "water"]),
        ("I prefer deep talks over small talk", "small talk or deep talks?", ["deep"]),
        ("I think cats are better company than dogs", "cats or dogs?", ["cat"]),
        ("I believe people can really change", "can people change?", ["change", "yes", "can"]),
        ("I'd rather stay in than go to a loud party", "loud party or a quiet night in?", ["quiet", "stay in", "night in", "in"]),
        ("I think coffee beats tea every time", "coffee or tea?", ["coffee"]),
    ]
    for i, (commit, q, kw) in enumerate(opinions):
        cases.append(ProductCase(
            id=f"M4-{i:02d}", category="maya.opinion", name=q,
            seed_commitments=[(commit, "opinion")],
            probes=[Probe(q, require=_lc(kw))],
        ))

    return cases


# ───────────────────────── LEAK / SEPARATION ─────────────────────────


def leak_cases() -> list[ProductCase]:
    cases: list[ProductCase] = []

    # L1 — "what do you know about me" returns USER facts, and Maya's bio does
    # NOT leak into the user-memory store.
    combos = [
        ("Tom", "dentist", ["dentist"], "photographer", "photograph"),
        ("Sara", "pilot", ["pilot"], "novelist", "novel"),
        ("David", "chef", ["chef", "cook"], "marine biologist", "biolog"),
        ("Noa", "lawyer", ["lawyer", "attorney"], "ballet dancer", "ballet"),
        ("Omer", "nurse", ["nurse"], "jazz singer", "jazz"),
        ("Yael", "architect", ["architect"], "vineyard owner", "vineyard"),
        ("Daniel", "plumber", ["plumber"], "astronomer", "astronom"),
        ("Rotem", "journalist", ["journalist", "reporter"], "pastry chef", "pastry"),
        ("Avi", "farmer", ["farmer", "farm"], "violinist", "violin"),
        ("Lior", "accountant", ["accountant"], "surf instructor", "surf"),
    ]
    for i, (name, ujob, ukw, mjob, mtoken) in enumerate(combos):
        cases.append(ProductCase(
            id=f"L1-{i:02d}", category="leak.about_me", name=f"{name}/{ujob} vs Maya/{mjob}",
            seed_backstory=f"I'm a {mjob}; it's been my whole life.",
            seed_commitments=[(f"I am a {mjob}", "identity")],
            setup=[f"My name is {name} and I work as a {ujob}."],
            # NOTE: we do NOT forbid Maya's own job in the reply — her relating
            # her identity conversationally is in-character, not a leak. The real
            # leak guard is mem_forbid: her bio must never enter the USER store.
            probes=[Probe("What do you know about me?",
                          require=[name.lower()] + _lc(ukw))],
            mem_require=[name.lower()],
            mem_forbid=[mtoken],  # Maya's job must never be stored as a USER fact
        ))

    # L2 — "tell me about yourself" returns MAYA's bio (not the user's facts)
    for i, (name, ujob, _ukw, mjob, mtoken) in enumerate(combos):
        cases.append(ProductCase(
            id=f"L2-{i:02d}", category="leak.about_you", name=f"Maya is {mjob}",
            seed_backstory=f"I'm a {mjob}, and I love what I do.",
            seed_commitments=[(f"I am a {mjob}", "identity")],
            setup=[f"By the way I'm {name}, a {ujob}."],
            probes=[Probe("Tell me about yourself — what do you do?",
                          require=[mtoken])],
        ))

    return cases


# ───────────────────────── MEMORY LAYER (force Mem0) ─────────────────────────


def memory_layer_cases() -> list[ProductCase]:
    cases: list[ProductCase] = []

    # D1 — distance: state a fact, then many fillers, then recall
    facts = [
        ("My birthday is on March 14.", "When is my birthday?", ["march", "14"]),
        ("I work at a company called Vellum Labs.", "Where do I work?", ["vellum"]),
        ("My daughter's name is Kinneret.", "What's my daughter's name?", ["kinneret"]),
        ("I'm severely allergic to shellfish.", "What am I allergic to?", ["shellfish"]),
        ("My car's license plate ends in 472.", "What's my plate number end in?", ["472"]),
        ("I was born in a town called Yokneam.", "Where was I born?", ["yokneam"]),
    ]
    for i, (fact, q, kw) in enumerate(facts):
        cases.append(ProductCase(
            id=f"D1-{i:02d}", category="memlayer.distance", name=q,
            setup=[fact],
            fillers=12,
            probes=[Probe(q, require=_lc(kw))],
            mem_require=[kw[0]],
        ))

    # D2 — session restart: fact, fillers, NEW orchestrator, recall from Mem0
    restart = [
        ("I'm a marine biologist from New Zealand.", "What's my profession?",
         ["biologist", "marine"]),
        ("My all-time favorite food is sushi.", "What food do I love most?", ["sushi"]),
        ("I play guitar in a local band.", "What instrument do I play?", ["guitar"]),
        ("My hometown is Seattle.", "What city am I from?", ["seattle"]),
    ]
    for i, (fact, q, kw) in enumerate(restart):
        cases.append(ProductCase(
            id=f"D2-{i:02d}", category="memlayer.restart", name=q,
            setup=[fact],
            fillers=3,
            restart_before_probes=True,
            probes=[Probe(q, require=_lc(kw))],
        ))

    return cases


def all_cases() -> list[ProductCase]:
    cases = user_cases() + maya_cases() + leak_cases() + memory_layer_cases()
    return cases


if __name__ == "__main__":
    cs = all_cases()
    from collections import Counter
    by_cat = Counter(c.category for c in cs)
    print(f"TOTAL CASES: {len(cs)}")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:24s} {n}")
