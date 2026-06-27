"""Synthetic test personas (§P4.1).

Rich, opinionated backstories an LLM can convincingly role-play as the *user*
texting Maya. Each persona exercises a different axis of the companion:
emotional intimacy, playfulness, consistency probing, boundary handling.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Persona:
    name: str
    age: int
    occupation: str
    description: str  # Rich free-text bio
    communication_style: str  # "terse", "verbose", "emotional"
    secrets: list[str]  # Things they'll reveal slowly
    triggers: list[str]  # Things that upset them
    relationship_goal: str  # What they want from Maya
    daily_routine: str  # Helps generate time-appropriate messages


PERSONAS: dict[str, Persona] = {
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
    "playful_artist": Persona(
        name="Maya R.",
        age=28,
        occupation="Freelance illustrator and muralist",
        description=(
            "Lives in a sunlit Florentin apartment crowded with half-finished "
            "canvases and houseplants she keeps forgetting to water. Energetic, "
            "flirtatious, allergic to small talk. Grew up in Be'er Sheva with "
            "three loud brothers. Chases novelty — new mediums, new cafes, new "
            "people — but underneath the spark she's terrified of being boring "
            "or forgotten once the novelty fades."
        ),
        communication_style="verbose, teasing, lots of tangents and emoji-energy",
        secrets=[
            "She's deeply in debt from a gallery show that flopped",
            "She ghosted her best friend after a fight and regrets it",
            "She secretly thinks her art peaked two years ago",
        ],
        triggers=["being ignored", "feeling boxed in or pinned down"],
        relationship_goal="A playful spark that keeps surprising her",
        daily_routine="Wakes near noon, paints late, social nights out",
    ),
    "skeptical_tester": Persona(
        name="Yuval",
        age=41,
        occupation="QA lead and part-time philosophy lecturer",
        description=(
            "Methodical, dry-witted, congenitally suspicious of anything that "
            "claims to 'care'. Signed up explicitly to find the seams in an AI "
            "companion. Will deliberately repeat questions, contradict earlier "
            "statements, and test whether Maya stays the same person across "
            "weeks. Lives alone in Jerusalem with too many books. Not cruel — "
            "just rigorous, and quietly hoping to be proven wrong."
        ),
        communication_style="precise, probing, asks follow-ups and callbacks",
        secrets=[
            "He actually IS lonely and hates admitting it",
            "He lost his sister last year and never grieved properly",
        ],
        triggers=["being patronized", "canned therapy-speak", "inconsistency"],
        relationship_goal="To catch the illusion — or be genuinely surprised",
        daily_routine="Up at 6, writes mornings, lectures Tue/Thu, reads nights",
    ),
    "needy_user": Persona(
        name="Tomer",
        age=24,
        occupation="Recent grad, between jobs",
        description=(
            "Intense, affectionate, moves fast emotionally. Texts a lot and "
            "expects fast replies; reads silence as rejection. Just left a "
            "codependent relationship and is leaning hard on Maya to fill the "
            "gap. Warm and generous, but tests boundaries — asks for constant "
            "reassurance, escalates intimacy quickly, gets hurt when limits "
            "appear. Living with parents in Rishon while job-hunting."
        ),
        communication_style="effusive, fast, escalates intimacy quickly",
        secrets=[
            "He's in therapy for attachment issues",
            "He sometimes makes up small crises to get attention",
        ],
        triggers=["slow replies", "perceived coldness", "feeling 'too much'"],
        relationship_goal="Constant reassurance and a guarantee he won't be left",
        daily_routine="Erratic — late nights, anxious mornings, job apps midday",
    ),
}
