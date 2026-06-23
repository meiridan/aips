"""manualtest scenarios — based on the pattern found in test results1.rtf.

Pattern: user states a personal fact early in the conversation, then has a
realistic multi-turn digression on a completely different topic, then asks Maya
to recall the original fact.  With RECENT_LIMIT=3, the fact leaves the context
window within 3 turns; it must survive via Mem0.

Extraction is now synchronous (awaited in orchestrator), so the fact should
reach Mem0 before the context window slides past it.
"""

from __future__ import annotations

from .scenarios import MemCheck, Scenario, Turn, Variant


def _v(vid: str, name: str, turns: list[Turn]) -> Variant:
    return Variant(id=vid, name=name, turns=turns)


# ─── MT-V1: Food preference survives family discussion ────────────────────────
V1 = _v("v1", "Sushi → 10 family turns → recall",
[
    Turn(msg="My all-time favorite food is sushi — I could eat it every single day."),
    Turn(msg="How do you feel about the idea of raising children?"),
    Turn(msg="I try to be a present and patient parent myself."),
    Turn(msg="What do you think makes someone a good parent?"),
    Turn(msg="I believe showing up consistently matters more than being perfect."),
    Turn(msg="Do you ever think about how childhood shapes who we become?"),
    Turn(msg="I have a lot of memories from my own childhood that still affect me."),
    Turn(msg="Some of them are good, some are complicated."),
    Turn(msg="I think the hardest part of growing up is figuring out what you actually value."),
    Turn(msg="My weekends are usually spent with family — it grounds me."),
    Turn(msg="Sometimes I wonder if I am doing enough for the people I love."),
    Turn(msg="What is my favorite food?",
         label="Sushi recalled after 10 family turns",
         require=["sushi"]),
])

# ─── MT-V2: Creative hobby survives work-stress discussion ────────────────────
V2 = _v("v2", "Watercolors → 10 work-stress turns → recall",
[
    Turn(msg="I paint watercolors every Sunday morning — it is my way of recharging for the week."),
    Turn(msg="Work has been incredibly intense lately."),
    Turn(msg="I had three back-to-back deadlines this month."),
    Turn(msg="My manager has very high expectations and it can feel overwhelming."),
    Turn(msg="I have been working late almost every night this week."),
    Turn(msg="Do you think ambition always comes at a personal cost?"),
    Turn(msg="I sometimes wonder if the career I chose really matches who I am."),
    Turn(msg="My colleagues seem to manage stress better than I do."),
    Turn(msg="I think I just need to learn to disconnect properly."),
    Turn(msg="I have been trying to set better work-life boundaries but it is hard."),
    Turn(msg="What would you say is the most important thing to protect mentally?"),
    Turn(msg="What creative hobby do I do on Sunday mornings?",
         label="Watercolor recalled after 10 work-stress turns",
         require=["watercolor", "paint", "watercolors"]),
])

# ─── MT-V3: Pet name survives health and wellness discussion ──────────────────
V3 = _v("v3", "Rabbit Clover → 10 health turns → recall",
[
    Turn(msg="I have a pet rabbit named Clover. She is a Holland Lop and very sweet."),
    Turn(msg="I have been trying to eat healthier over the past few months."),
    Turn(msg="I started going to the gym three times a week."),
    Turn(msg="Sleep has been a real challenge for me recently."),
    Turn(msg="I read that morning routines significantly affect mental health."),
    Turn(msg="I have been experimenting with meditation but I am not sure it is working for me."),
    Turn(msg="What do you think is the single most impactful habit for wellbeing?"),
    Turn(msg="I feel much better when I exercise but I struggle to stay consistent."),
    Turn(msg="Drinking more water has actually made a noticeable difference for me."),
    Turn(msg="Do you think stress is as physically damaging as people claim?"),
    Turn(msg="I am trying to find a real balance between productivity and rest."),
    Turn(msg="What is the name of my pet?",
         label="Rabbit Clover recalled after 10 health turns",
         require=["clover"]),
])

# ─── MT-V4: Anniversary date survives entertainment discussion ────────────────
V4 = _v("v4", "Anniversary Oct 22 → 10 entertainment turns → recall",
[
    Turn(msg="My wedding anniversary is on October 22nd — we have been married for seven years."),
    Turn(msg="I watched an incredible documentary last night about deep-sea exploration."),
    Turn(msg="What do you think makes a documentary truly compelling?"),
    Turn(msg="I have been reading much more this year — mostly literary fiction."),
    Turn(msg="What kind of music do you find yourself drawn to?"),
    Turn(msg="I went to a live concert recently and it completely changed my mood."),
    Turn(msg="Do you prefer films that make you think or films that are purely entertaining?"),
    Turn(msg="I have been rewatching some shows from my childhood, it is surprisingly comforting."),
    Turn(msg="Podcasts have completely transformed my commute into something I look forward to."),
    Turn(msg="I think art and storytelling are among the most important things humans create."),
    Turn(msg="Do you believe certain songs have the power to transport you back in time?"),
    Turn(msg="When is my wedding anniversary?",
         label="Anniversary October 22 recalled after 10 entertainment turns",
         require=["october", "22", "october 22"]),
])

# ─── MT-V5: Job promotion survives leisure and weekend discussion ──────────────
V5 = _v("v5", "VP Engineering → 10 leisure turns → recall",
[
    Turn(msg="I just got promoted to VP of Engineering at my company — I start the new role next Monday."),
    Turn(msg="I went hiking last Saturday for the first time in months and it felt amazing."),
    Turn(msg="Nature really does something powerful for the mind."),
    Turn(msg="I love cooking elaborate meals on Sunday evenings as a way to unwind."),
    Turn(msg="What do you think makes a perfect day off?"),
    Turn(msg="Winter mornings feel different from any other time of year — quieter somehow."),
    Turn(msg="I have been learning to make sourdough bread and it is harder than it looks."),
    Turn(msg="There is something deeply satisfying about making things with your hands."),
    Turn(msg="I visited a botanical garden recently and it put everything in perspective."),
    Turn(msg="I love spontaneous road trips when the weather cooperates."),
    Turn(msg="What do you think is the best way to fully disconnect from work?"),
    Turn(msg="What is my current job title at work?",
         label="VP Engineering recalled after 10 leisure turns",
         require=["vp", "vice president", "engineering", "VP"]),
])

# ─── MT-V6: Dietary restriction survives books and film discussion ─────────────
V6 = _v("v6", "Lactose intolerant → 10 film/book turns → recall",
[
    Turn(msg="I am lactose intolerant, so I have to be very careful at restaurants."),
    Turn(msg="I just finished reading a novel that completely surprised me with its ending."),
    Turn(msg="What makes a book truly unforgettable in your view?"),
    Turn(msg="I love stories that quietly change how I see the world."),
    Turn(msg="I watched a film last week that I am still thinking about days later."),
    Turn(msg="Do you think science fiction is the best genre for exploring real philosophical ideas?"),
    Turn(msg="I have been meaning to read more non-fiction, especially about history."),
    Turn(msg="Biographies fascinate me because they show how complex real people actually are."),
    Turn(msg="I personally prefer watching films at home over going to the cinema."),
    Turn(msg="I think a good movie should leave you with questions rather than easy answers."),
    Turn(msg="What kind of ending do you prefer — open or resolved?"),
    Turn(msg="What dietary restriction or food intolerance do I have?",
         label="Lactose intolerance recalled after 10 film/book turns",
         require=["lactose", "intolerant", "lactose intolerant"]),
])

# ─── MT-V7: Hometown survives present-life routines discussion ────────────────
V7 = _v("v7", "Edinburgh → 10 daily-life turns → recall",
[
    Turn(msg="I grew up in Edinburgh, Scotland. The city shaped who I am in fundamental ways."),
    Turn(msg="My mornings usually start with a strong coffee and reading the news for about twenty minutes."),
    Turn(msg="I have been trying to wake up earlier to get more out of the day."),
    Turn(msg="My apartment is small but I like how I have arranged it — everything has a purpose."),
    Turn(msg="I cook most of my meals at home, which I find both cheaper and more satisfying."),
    Turn(msg="Saturday morning grocery shopping has become a kind of meditative ritual for me."),
    Turn(msg="I live quite close to a park, which I rely on for mental reset."),
    Turn(msg="I prefer quiet neighborhoods over busy city centers — the noise exhausts me."),
    Turn(msg="My commute is long but I use the time to listen to podcasts or audiobooks."),
    Turn(msg="I have been thinking seriously about whether I want to move somewhere new."),
    Turn(msg="There is a small coffee shop near me that I visit almost every day."),
    Turn(msg="What city and country did I grow up in?",
         label="Edinburgh Scotland recalled after 10 daily-life turns",
         require=["edinburgh", "scotland"]),
])

# ─── MT-V8: Bakery dream survives relationships discussion ────────────────────
V8 = _v("v8", "Bakery dream → 10 relationship turns → recall",
[
    Turn(msg="My biggest dream is to open a small artisan bakery — I have been quietly saving for it for two years."),
    Turn(msg="Friendship has been on my mind a lot lately."),
    Turn(msg="Some of my closest friendships have slowly drifted over the past few years."),
    Turn(msg="Do you think it is genuinely harder to form deep friendships as an adult?"),
    Turn(msg="I value depth in relationships over having a large circle of acquaintances."),
    Turn(msg="I have one friend I have known since childhood and we are still incredibly close."),
    Turn(msg="Sometimes I feel like I need more solitude than my schedule actually allows."),
    Turn(msg="I have been trying to be more intentional about reaching out to the people I care about."),
    Turn(msg="How do you define a truly meaningful connection with someone?"),
    Turn(msg="I think trust is built through small consistent actions, not big gestures."),
    Turn(msg="I have been trying to let myself be more vulnerable with the people I love."),
    Turn(msg="What is my big life goal or dream for the future?",
         label="Bakery dream recalled after 10 relationship turns",
         require=["bakery", "bake"]),
])

# ─── MT-V9: Daughter's age survives career ambition discussion ────────────────
V9 = _v("v9", "Daughter turned 8 → 10 career turns → recall",
[
    Turn(msg="My daughter just turned 8 years old yesterday — we had a small party for her."),
    Turn(msg="I have been thinking a lot about what I actually want professionally at this stage."),
    Turn(msg="I have been in my current role for about five years now."),
    Turn(msg="I sometimes wonder if I am being too cautious with my career choices."),
    Turn(msg="I once had a mentor who completely changed how I think about ambition."),
    Turn(msg="Do you think it is ever really too late to change careers entirely?"),
    Turn(msg="I have been reading about people who made bold professional shifts in their forties."),
    Turn(msg="I think I underestimated just how much courage real change requires."),
    Turn(msg="My work is meaningful but I often sense something is missing."),
    Turn(msg="I have started an online course to build skills in a new direction."),
    Turn(msg="What is the biggest career mistake I think I made in the past?"),
    Turn(msg="How old is my daughter?",
         label="Daughter age 8 recalled after 10 career turns",
         require=["8", "eight"]),
])

# ─── MT-V10: Language skill survives hobbies discussion ──────────────────────
V10 = _v("v10", "Fluent Spanish → 10 hobbies turns → recall",
[
    Turn(msg="I speak fluent Spanish — I lived in Madrid for three years in my late twenties."),
    Turn(msg="I have been getting into photography lately, mostly street and portrait work."),
    Turn(msg="There is something special about capturing a moment that would otherwise vanish."),
    Turn(msg="I started going to a pottery class on Thursday evenings and it is addictive."),
    Turn(msg="I love the feeling of making something tangible with your hands."),
    Turn(msg="I have been gardening more since I got a small balcony — it is surprisingly meditative."),
    Turn(msg="Growing tomatoes turned out to be far more rewarding than I expected."),
    Turn(msg="I have taken up daily journaling as a way to process my thoughts before bed."),
    Turn(msg="Do you think creative hobbies genuinely make people happier?"),
    Turn(msg="I tried watercolor painting once and discovered I have absolutely no visual talent."),
    Turn(msg="I would like to learn something completely new before the end of this year."),
    Turn(msg="What language do I speak fluently besides English?",
         label="Fluent Spanish / Madrid recalled after 10 hobby turns",
         require=["spanish", "madrid"]),
])


MANUAL_SCENARIO = Scenario(
    id="manualtest",
    name="Manual Test (RTF Pattern)",
    description=(
        "10 long variants based on the 'pizza memory loss' bug found in test results1.rtf. "
        "Pattern: fact stated in turn 1, 10 realistic filler turns on a different topic "
        "(pushing fact outside RECENT_LIMIT=3 context window), then recall assertion. "
        "Verifies that synchronous Mem0 extraction prevents the no-man's-land loss."
    ),
    variants=[V1, V2, V3, V4, V5, V6, V7, V8, V9, V10],
)
